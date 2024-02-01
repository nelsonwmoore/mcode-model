"""load mCODE model and convert to MDF"""

import re
from typing import Any

import polars as pl
import requests
from bento_mdf.mdf import MDF
from bento_meta.model import Model
from bento_meta.objects import Node, Property, Term, ValueSet
from icecream import ic

# constants
MCODE_HDL = "mCODE"
DATA_PATH = "../data/"
MCODE_FILE = DATA_PATH + "mCODEDataDictionary-STU3.xlsx"
MCODE_TERMS_FILE = DATA_PATH + "mCode_Terminology.xlsx"
MDF_PATH = "../../model-desc/mcode-model.yml"


def to_snake_case(string: str) -> str:
    """converts given string to snake case representation"""
    string = string.replace(" ", "_")
    string = re.sub(r"(?<=[a-z0-9])_?([A-Z])", r"_\1", string)
    return string.lower()


def row_to_node(row: dict[str, Any]) -> Node:
    """convert row of profiles df to a node"""
    return Node(
        {
            "handle": to_snake_case(row["Title"]),
            "desc": row["Description"],
            "model": MCODE_HDL,
        }
    )


def row_to_prop(row: dict[str, Any]) -> Property:
    """convert row of data elements df to a property"""
    prop = Property(
        {
            "handle": to_snake_case(row["Data Element Name"]),
            "desc": row["Definition"],
            "_parent_handle": to_snake_case(row["Profile Title"]),
            "is_required": row["Required?"] == "Required",
        }
    )
    if row["Value Set URI"]:
        prop.value_domain = "value_set"
        prop.value_set = get_valset_from_url(row["Value Set URI"])
    else:
        domain = row["Data Type"].lower()
        if domain in {"number", "integer", "string", "datetime", "url", "boolean"}:
            prop.value_domain = domain
        else:
            prop.value_domain = "TBD"
    return prop


def row_to_term(row: dict[str, Any], is_terms_df: bool = False) -> Term:
    """convert row of filtered term df to a bento-meta Term"""
    hdl_key = "mCode PT" if is_terms_df else "Code Description"
    code_key = "Source Code" if is_terms_df else "Code"
    origin_key = "Code System"
    term = Term(
        {
            "handle": to_snake_case(row[hdl_key]),
            "value": row[hdl_key],
            "origin_id": row[code_key],
            "origin_name": row[origin_key],
        }
    )
    return term


def get_nodes_from_df(df: pl.DataFrame) -> list[Node]:
    """get nodes from mcode profiles df"""
    return [row_to_node(row=row) for row in df.iter_rows(named=True)]


def get_props_from_df(df: pl.DataFrame) -> list[Property]:
    """get nodes from mcode profiles df"""
    return [row_to_prop(row=row) for row in df.iter_rows(named=True)]


def get_terms_from_df(df: pl.DataFrame, is_terms_df: bool = False) -> list[Term]:
    """get nodes from mcode profiles df"""
    return [
        row_to_term(row=row, is_terms_df=is_terms_df)
        for row in df.iter_rows(named=True)
    ]


def get_valset_from_url(url: str) -> ValueSet:
    """get valueset with terms from mcode url"""
    vs = ValueSet({"url": url})
    vs_title = get_vs_title_from_url(url)

    terms_df = get_terms_df_by_vs_title(vs_codes_df_filtered, vs_title)
    if not terms_df.is_empty():  # vs in vs_codes_df
        vs.terms = {t.handle: t for t in get_terms_from_df(terms_df, is_terms_df=False)}
        return vs
    # vs not in vs_codes_df
    terms_df = get_terms_df_by_vs_title(
        mcode_terms_df_filtered, vs_title, is_terms_df=True
    )
    if not terms_df.is_empty():
        vs.terms = {t.handle: t for t in get_terms_from_df(terms_df, is_terms_df=True)}
        return vs
    return vs


def get_vs_title_from_url(url: str) -> str:
    """get valueset with terms from mcode url"""
    if extract_domain(url) == "hl7.org" and "mcode" in url:
        vs_json = get_mcode_vs_json(url)
    elif extract_domain(url) == "hl7.org":
        vs_json = get_fhir_vs_json(url)
    else:
        vs_json = {}

    return vs_json.get("title", "")


def format_mcode_vs_url(url: str) -> str:
    """format mcode hl7 value set url"""
    return url.replace("ValueSet/", "ValueSet-") + ".json"


def format_fhir_vs_url(url: str) -> str:
    """format fhir hl7 value set url"""
    return (
        url.replace("http://hl7.org/fhir/", "https://hl7.org/fhir/codesystem-")
        + ".json"
    )


def get_mcode_vs_json(url: str) -> dict:
    """get raw json from mcode url"""
    json_vs_url = format_mcode_vs_url(url)
    try:
        response = requests.get(json_vs_url, timeout=5)
        if response.status_code == 200:
            return response.json()
        ic(f"Error: {response.status_code} at url {json_vs_url} from url {url}")
    except Exception as e:
        ic(f"An error occurred attempting to access {json_vs_url} from url {url}: {e}")
    return {}


def get_fhir_vs_json(url: str) -> dict:
    """get raw json from fhir url (non mcode)"""
    json_vs_url = format_fhir_vs_url(url)
    try:
        response = requests.get(json_vs_url, timeout=5)
        if response.status_code == 200:
            return response.json()
        # retry w/ diff url
        elif response.status_code == 404:
            json_vs_url = (
                url.replace("ValueSet/", "valueset-").split("|", 1)[0] + ".json"
            )
            response = requests.get(json_vs_url, timeout=5)
            return response.json()
        ic(f"Error: {response.status_code} at url {json_vs_url} from url {url}")
    except Exception as e:
        ic(f"An error occurred attempting to access {json_vs_url} from url {url}: {e}")
    return {}


def get_terms_df_by_vs_title(
    df: pl.DataFrame, vs_title: str, is_terms_df: bool = False
) -> pl.DataFrame:
    """get vs terms from mcode value set codes by vs title"""
    if vs_title == "":
        return pl.DataFrame()
    if is_terms_df:
        vs_title = "mCode " + vs_title
    vs_df_filtered = df.filter(df["Value Set Name"] == vs_title)
    if vs_df_filtered.is_empty():
        return pl.DataFrame()
    return vs_df_filtered


def get_col_count(df: pl.DataFrame, col: str) -> pl.DataFrame:
    """Returns a df with count of unique values in given column"""
    source_counts_df = df.group_by(by=col).agg(pl.col(col).count().alias("Count"))
    return source_counts_df.sort(by="Count", descending=True)


def extract_domain(url: str) -> str:
    """get domain from url string"""
    url = url.split("http://", 1)[-1]
    url = url.split("/", 1)[0]
    return url


if __name__ == "__main__":
    # get dfs
    profile_df = pl.read_excel(source=MCODE_FILE, sheet_name="Profiles")
    de_df = pl.read_excel(source=MCODE_FILE, sheet_name="Data elements")
    vs_df = pl.read_excel(source=MCODE_FILE, sheet_name="Value sets")
    vs_codes_df = pl.read_excel(source=MCODE_FILE, sheet_name="Value set codes")
    vs_codes_df_filtered = vs_codes_df.filter(vs_codes_df["Code"].is_not_null())
    mcode_terms_df = pl.read_excel(
        source=MCODE_TERMS_FILE,
        sheet_name="23.11d",
        read_csv_options={"infer_schema_length": 0},
    )
    mcode_terms_df_filtered = mcode_terms_df.filter(
        mcode_terms_df["Value Set Name"] != "mCode Terminology"
    )

    # get bento-meta objs
    # model
    model = Model(handle="mCODE")

    # nodes
    nodes = get_nodes_from_df(df=profile_df)
    model.nodes = {n.handle: n for n in nodes}

    # props
    props = get_props_from_df(df=de_df)
    for prop in props:
        parent = model.nodes[prop._parent_handle]
        parent.props[prop.handle] = prop
    model.props = {(p._parent_handle, p.handle): p for p in props}

    # terms
    terms_1 = get_terms_from_df(df=vs_codes_df_filtered, is_terms_df=False)
    terms_1_d = {(t.handle, t.origin_name): t for t in terms_1}
    terms_2 = get_terms_from_df(df=mcode_terms_df_filtered, is_terms_df=True)
    terms_2_d = {(t.handle, t.origin_name): t for t in terms_2}
    merged_terms = {**terms_2_d, **terms_1_d}
    model.terms = merged_terms

    # save model to mdf?
    mcode_mdf = MDF(handle=MCODE_HDL, model=model)
    mcode_mdf.write_mdf(file=MDF_PATH)
