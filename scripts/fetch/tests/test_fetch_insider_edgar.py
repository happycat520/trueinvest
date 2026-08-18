#!/usr/bin/env python3
"""
Tests fetch_insider_edgar.py's XML parsing against a hand-built mock Form 4
matching the real SEC ownership-document schema. This is the substitute for
a live end-to-end test, since this build environment can't reach
www.sec.gov / data.sec.gov (network sandbox restriction) - see the
NOT TESTED AGAINST LIVE SEC.GOV notice at the top of fetch_insider_edgar.py.

Run: python3 test_fetch_insider_edgar.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fetch_insider_edgar import (
    parse_form4_xml, parse_role, build_document_url, build_filing_index_url,
)

MOCK_XML_PATH = Path(__file__).resolve().parent / "mock_form4.xml"


def test_parse_form4_xml():
    xml_bytes = MOCK_XML_PATH.read_bytes()
    transactions = parse_form4_xml(
        xml_bytes,
        ticker="ACME",
        company="Example Robotics Inc",
        cik="0000320193",
        accession_number="0001234567-26-000456",
    )

    assert len(transactions) == 2, f"expected 2 transactions, got {len(transactions)}"

    buy = transactions[0]
    assert buy["code"] == "P", buy["code"]
    assert buy["shares"] == 15000, buy["shares"]
    assert buy["price"] == 12.40, buy["price"]
    assert buy["value"] == 186000.0, buy["value"]
    assert buy["insider"] == "RUIZ JANE", buy["insider"]
    assert buy["role"] == "Chief Financial Officer", buy["role"]
    assert buy["date"] == "2026-08-12", buy["date"]
    assert buy["shares_owned_after"] == 84200, buy["shares_owned_after"]
    print("  PASS: buy (code P) parsed correctly ->", buy["shares"], "shares @", buy["price"], "=", buy["value"])

    tax_withholding = transactions[1]
    assert tax_withholding["code"] == "F", tax_withholding["code"]
    print("  PASS: non-open-market transaction (code F) parsed but correctly distinguishable for filtering")

    # Confirm the main script's buy/sell classification would keep only the P
    # and correctly EXCLUDE the F (tax withholding is not a buy or sell signal)
    from fetch_insider_edgar import BUY_CODES, SELL_CODES
    classified_buys = [t for t in transactions if t["code"] in BUY_CODES]
    classified_sells = [t for t in transactions if t["code"] in SELL_CODES]
    assert len(classified_buys) == 1, classified_buys
    assert len(classified_sells) == 0, classified_sells
    print("  PASS: classification correctly keeps 1 buy, 0 sells (F code excluded from both)")


def test_url_construction():
    doc_url = build_document_url("0000320193", "0001234567-26-000456", "primary_doc.xml")
    expected_doc = "https://www.sec.gov/Archives/edgar/data/320193/000123456726000456/primary_doc.xml"
    assert doc_url == expected_doc, doc_url
    print("  PASS: document URL ->", doc_url)

    index_url = build_filing_index_url("0000320193", "0001234567-26-000456")
    expected_index = "https://www.sec.gov/Archives/edgar/data/320193/000123456726000456/0001234567-26-000456-index.htm"
    assert index_url == expected_index, index_url
    print("  PASS: filing index URL ->", index_url)


def test_role_parsing_variants():
    import xml.etree.ElementTree as ET

    director_xml = """<reportingOwner>
        <reportingOwnerRelationship>
            <isDirector>1</isDirector>
            <isOfficer>0</isOfficer>
            <isTenPercentOwner>0</isTenPercentOwner>
        </reportingOwnerRelationship>
    </reportingOwner>"""
    el = ET.fromstring(director_xml)
    assert parse_role(el) == "Director", parse_role(el)
    print("  PASS: director-only relationship -> 'Director'")

    ten_pct_xml = """<reportingOwner>
        <reportingOwnerRelationship>
            <isDirector>0</isDirector>
            <isOfficer>0</isOfficer>
            <isTenPercentOwner>1</isTenPercentOwner>
        </reportingOwnerRelationship>
    </reportingOwner>"""
    el = ET.fromstring(ten_pct_xml)
    assert parse_role(el) == "10% Owner", parse_role(el)
    print("  PASS: 10%-owner-only relationship -> '10% Owner'")

    ceo_xml = """<reportingOwner>
        <reportingOwnerRelationship>
            <isDirector>1</isDirector>
            <isOfficer>1</isOfficer>
            <isTenPercentOwner>0</isTenPercentOwner>
            <officerTitle>Chief Executive Officer</officerTitle>
        </reportingOwnerRelationship>
    </reportingOwner>"""
    el = ET.fromstring(ceo_xml)
    assert parse_role(el) == "Chief Executive Officer", parse_role(el)
    print("  PASS: officer title takes priority over director flag -> 'Chief Executive Officer'")


if __name__ == "__main__":
    print("test_parse_form4_xml:")
    test_parse_form4_xml()
    print("\ntest_url_construction:")
    test_url_construction()
    print("\ntest_role_parsing_variants:")
    test_role_parsing_variants()
    print("\nAll tests passed.")
