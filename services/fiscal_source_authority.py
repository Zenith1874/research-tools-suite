"""Narrow authority boundary for reviewed primary provincial issuer documents."""
from urllib.parse import urlsplit, urlunsplit
from services.provincial_fiscal_visual_expansion import FIVE_APPROVED_VISUAL_FILINGS
from services.provincial_fiscal_six_profiles import SIX_APPROVED_VISUAL_FILINGS, SIX_APPROVED_TEXT_FILINGS


SHAANXI_ISSUER_URL = 'https://static.sse.com.cn/disclosure/bond/announcement/local/c/new/2026-04-22/0000_20260422_X55R.pdf'
SHAANXI_ISSUER_SHA256 = 'a1c1e460a49465c73bc299c849da977f30eac95f56a7037ca165b1499a77eebf'
SHAANXI_ISSUER_TITLE = '2026年陕西省政府专项债券（四至九期）信息披露文件'
HUBEI_ANNEX_URL = 'https://static.sse.com.cn/disclosure/bond/announcement/local/c/new/2026-04-10/0000_20260410_XVTA.pdf'
HUBEI_ANNEX_SHA256 = '640c785483ca6d90fca6f99bc4e5e9ef6f28f1f205e032d1322eb95be148e564'
HUBEI_ANNEX_TITLE = '附件2：湖北省（区、市）经济、财政和债务有关数据'

# Acquisition-only candidates. These do not authorize observation ingestion;
# that still requires the separate reviewed source/hash/page policy below.
DISCOVERY_TRANSPORT_URLS = {
    'https://www.governbond.org.cn/uploadFiles/22/attachFiles/202609/f552e29c-165f-41ce-896b-172fca6d834e.pdf': 'official_platform_document',
    'https://www.governbond.org.cn/uploadFiles/23/attachFiles/202610/c1e4f5df-60e0-498c-a6e4-2f5024fc613a.pdf': 'official_platform_document',
    'https://www.governbond.org.cn/uploadFiles/33/attachFiles/202609/56d2cb39-74f1-435e-9aa0-b857cdb397c6.pdf': 'official_platform_document',
    'https://www.governbond.org.cn/uploadFiles/37/attachFiles/202609/3a8e04f3-5529-4b5a-8e42-75cb166122c3.pdf': 'official_platform_document',
    'https://www.governbond.org.cn/uploadFiles/41/attachFiles/202609/d2a0bb1b-d903-444e-80a7-0c1c727fbdfe.pdf': 'official_platform_document',
    'https://www.governbond.org.cn/uploadFiles/44/attachFiles/202609/7ebf04ba-2f44-441f-9dd0-bed3053f8eb8.pdf': 'official_platform_document',
    'https://www.celma.org.cn/fxqgg/70427.jhtml': 'official_platform_catalog',
    'https://www.celma.org.cn/fxqgg/70678.jhtml': 'official_platform_catalog',
    'https://www.celma.org.cn/fxqgg/70549.jhtml': 'official_platform_catalog',
    'https://www.celma.org.cn/fxqgg/70616.jhtml': 'official_platform_catalog',
    'https://www.celma.org.cn/fxqgg/70563.jhtml': 'official_platform_catalog',
    'https://www.celma.org.cn/fxqgg/70579.jhtml': 'official_platform_catalog',
    'https://www.governbond.org.cn/uploadFiles/11/attachFiles/202609/80c19e2b-b334-46c8-b715-97168a6aa0b8.pdf': 'official_platform_document',
    'https://www.governbond.org.cn/uploadFiles/12/attachFiles/202607/9244984c-8679-4aab-81c6-92df0eb4d705.pdf': 'official_platform_document',
    'https://www.governbond.org.cn/uploadFiles/13/attachFiles/202609/ae060c7a-1b61-4dca-801e-1ddfd4a1c570.pdf': 'official_platform_document',
    'https://www.governbond.org.cn/uploadFiles/14/attachFiles/202609/47050154-cd87-4b88-babf-ed9d11707969.pdf': 'official_platform_document',
    'https://www.governbond.org.cn/uploadFiles/21/attachFiles/202608/d75e0dad-64c3-440c-a088-393b969b7e8e.pdf': 'official_platform_document',
    'https://www.celma.org.cn/fxqgg/70515.jhtml': 'official_platform_catalog',
    'https://www.celma.org.cn/fxqgg/69900.jhtml': 'official_platform_catalog',
    'https://www.celma.org.cn/fxqgg/70620.jhtml': 'official_platform_catalog',
    'https://www.celma.org.cn/fxqgg/70548.jhtml': 'official_platform_catalog',
    'https://www.celma.org.cn/fxqgg/70293.jhtml': 'official_platform_catalog',
    'https://static.sse.com.cn/disclosure/bond/announcement/local/c/new/2026-04-10/0000_20260410_XVTA.pdf': 'government_issuer_filing',
    'https://static.sse.com.cn/disclosure/bond/announcement/local/c/new/2026-09-10/0000_20260910_SI8F.pdf': 'government_issuer_filing',
    'https://static.sse.com.cn/disclosure/bond/announcement/local/c/new/2026-09-15/0000_20260915_7T4J.pdf': 'government_issuer_filing',
    'https://static.sse.com.cn/disclosure/bond/announcement/local/c/new/2026-02-12/0000_20260212_WYMC.pdf': 'government_issuer_filing',
    'https://www.celma.org.cn/fxqgg/68564.jhtml': 'official_platform_catalog',
    'https://www.celma.org.cn/cxqpl/69622.jhtml': 'official_platform_catalog',
    'https://www.celma.org.cn/fxqgg/index.jhtml': 'official_platform_catalog',
    'https://www.celma.org.cn/fxqgg/70478.jhtml': 'official_platform_catalog',
    'https://www.governbond.org.cn/uploadFiles/45/attachFiles/202604/13b6eca2-b017-4c12-b2d3-089c267c260d.pdf': 'official_platform_document',
    'https://www.governbond.org.cn/uploadFiles/52/attachFiles/202606/e96c5828-1763-4ae4-8eb1-87ff91460118.pdf': 'official_platform_document',
    'https://www.governbond.org.cn/uploadFiles/52/attachFiles/202609/10aef2fd-1ce9-4920-9315-bcd41f25a349.pdf': 'official_platform_document',
}


def official_fiscal_download_url(url, source_class='government_website'):
    parts = urlsplit(url)
    if parts.scheme != 'https' or parts.username or parts.password:
        return False
    if (parts.hostname or '').endswith('.gov.cn'):
        return True
    # No general exchange/company/rating crawl: only this discovered filing.
    return ((source_class == 'government_issuer_filing' and url == SHAANXI_ISSUER_URL)
            or (url in DISCOVERY_TRANSPORT_URLS and DISCOVERY_TRANSPORT_URLS[url] == source_class))


APPROVED_VISUAL_FILINGS = {
    "https://www.governbond.org.cn/uploadFiles/45/attachFiles/202604/13b6eca2-b017-4c12-b2d3-089c267c260d.pdf": {
        "region_code": "450000",
        "region_name": "广西",
        "source_name": "广西壮族自治区财政厅（财政部地方债信息公开平台原始披露）",
        "source_title": "2026年广西壮族自治区政府专项债券（七至十一期）信息披露文件",
        "source_class": "official_platform_document",
        "raw_sha256": "ba458477709cd698e199519d77b5896b269716d9bcff31fefdf7d6057653467f",
        "transcript_sha256": "5d31a5b2b078469c0fab4ccd8112a3e7b51ae66317345b989ef425ccf340fc36",
        "page_by_code": {
            "general_budget_revenue": 6,
            "general_budget_expenditure": 6,
            "gov_fund_revenue": 6,
            "gov_fund_expenditure": 6,
            "debt_outstanding": {
                "2024": 6,
                "2025": 7
            },
            "general_debt_outstanding": {
                "2025": 7
            }
        },
        "fiscal_status": {
            "2023": "official",
            "2024": "official",
            "2025": "official"
        }
    },
    "https://static.sse.com.cn/disclosure/bond/announcement/local/c/new/2026-09-10/0000_20260910_SI8F.pdf": {
        "region_code": "340000",
        "region_name": "安徽",
        "source_name": "安徽省财政厅（上交所政府债券发行人原始披露）",
        "source_title": "2026年安徽省政府专项债券（六十四～七十五期）信息披露文件",
        "source_class": "government_issuer_filing",
        "raw_sha256": "8b4cc7e699f160b523dd5add3f35deed1b6e512db832801a2ffe5e3b25d8fb06",
        "transcript_sha256": "2147a4be9123a2ccb607ce6fe9b984975027372afc6e027d3a1aaf8537413ff9",
        "page_by_code": {
            "general_budget_revenue": 5,
            "general_budget_expenditure": 5,
            "gov_fund_revenue": 5,
            "gov_fund_expenditure": 6,
            "land_transfer_revenue": 6,
            "debt_outstanding": {
                "2025": 6
            },
            "general_debt_outstanding": {
                "2025": 6
            }
        },
        "fiscal_status": {
            "2023": "official_final",
            "2024": "official_final",
            "2025": "official_final"
        }
    },
    "https://static.sse.com.cn/disclosure/bond/announcement/local/c/new/2026-09-15/0000_20260915_7T4J.pdf": {
        "region_code": "500000",
        "region_name": "重庆",
        "source_name": "重庆市财政局（上交所政府债券发行人原始披露）",
        "source_title": "2026年重庆市政府专项债券（三十期至三十四期）信息披露文件",
        "source_class": "government_issuer_filing",
        "raw_sha256": "9719caa6d402dae8f27d250df9727bede74172ee826f319ea0641f8b67d9d451",
        "transcript_sha256": "e6dadf774a7e8df9a5ceab232fcf5b92a5684a29d36f4c30d8f57941be7dfdd3",
        "page_by_code": {
            "general_budget_revenue": 7,
            "general_budget_expenditure": 7,
            "gov_fund_revenue": 8,
            "gov_fund_expenditure": 8,
            "land_transfer_revenue": 8,
            "debt_outstanding": {
                "2025": 9
            }
        },
        "fiscal_status": {
            "2023": "official_final",
            "2024": "official_final",
            "2025": "official_final"
        }
    },
    "https://www.governbond.org.cn/uploadFiles/52/attachFiles/202609/10aef2fd-1ce9-4920-9315-bcd41f25a349.pdf": {
        "region_code": "520000",
        "region_name": "贵州",
        "source_name": "贵州省财政厅（财政部地方债信息公开平台原始披露）",
        "source_title": "2026年第七批贵州省地方政府债券信息披露文件",
        "source_class": "official_platform_document",
        "raw_sha256": "53a4016995a0a936790fbce3b2accdee09ea2abd0e4cd25701838287e50409ac",
        "transcript_sha256": "d1892de1b9543af931ede15d935fee8dcaceb2d91592b54aa8abca63e423f518",
        "page_by_code": {
            "general_budget_revenue": 12,
            "general_budget_expenditure": 12,
            "gov_fund_revenue": 12,
            "gov_fund_expenditure": 12,
            "debt_outstanding": {
                "2025": 8
            },
            "general_debt_outstanding": {
                "2025": 8
            }
        },
        "fiscal_status": {
            "2023": "official_final",
            "2024": "official_final",
            "2025": "official_preliminary"
        }
    }
}


APPROVED_VISUAL_FILINGS.update(FIVE_APPROVED_VISUAL_FILINGS)
APPROVED_VISUAL_FILINGS.update(SIX_APPROVED_VISUAL_FILINGS)


def reviewed_visual_fiscal_source(row, base, fragment):
    spec=APPROVED_VISUAL_FILINGS.get(base)
    if not spec:return False
    period=str(row.get('period',''));code=row.get('indicator_code')
    page=spec['page_by_code'].get(code)
    if isinstance(page,dict):page=page.get(period)
    if page is None or period not in spec['fiscal_status']:return False
    status=spec.get('debt_status',{}).get(period,'official') if code.endswith('debt_outstanding') else spec['fiscal_status'][period]
    notes=row.get('parser_notes','')
    return (all(row.get(k)==spec[k] for k in ('region_code','region_name','source_name','source_title'))
            and row.get('data_status')==status and fragment=='page='+str(page)
            and 'access_type='+spec['source_class'] in notes
            and 'raw_sha256='+spec['raw_sha256'] in notes
            and 'visual_transcript_sha256='+spec['transcript_sha256'] in notes
            and 'parse_mode=reviewed_visual_transcript' in notes
            and 'unit_evidence=explicit_source_heading' in notes)


def reviewed_issuer_fiscal_source(row):
    """Bind the exception to the inspected issuer, source bytes, pages and years."""
    parts = urlsplit(row.get('source_url', ''))
    base = urlunsplit(parts._replace(fragment=''))
    if base in APPROVED_VISUAL_FILINGS:
        return reviewed_visual_fiscal_source(row,base,parts.fragment)
    if base in SIX_APPROVED_TEXT_FILINGS:
        spec = SIX_APPROVED_TEXT_FILINGS[base]
        period = str(row.get('period', ''))
        page = spec['page_by_code'].get(row.get('indicator_code'))
        if isinstance(page, dict):
            page = page.get(period)
        notes = row.get('parser_notes', '')
        return (page is not None and period in spec['fiscal_status']
                and all(row.get(k) == spec[k] for k in ('region_code', 'region_name', 'source_name', 'source_title'))
                and parts.fragment == 'page=' + str(page)
                and row.get('data_status') == spec['fiscal_status'][period]
                and 'access_type=' + spec['source_class'] in notes
                and 'raw_sha256=' + spec['raw_sha256'] in notes
                and 'parse_mode=reviewed_text_layer' in notes
                and 'unit_evidence=explicit_source_heading' in notes)
    period = str(row.get('period', ''))
    if base == HUBEI_ANNEX_URL:
        code = row.get('indicator_code')
        notes = row.get('parser_notes','')
        return (row.get('region_code')=='420000' and row.get('region_name')=='湖北'
                and row.get('source_name')=='湖北省地方政府债券披露附件（上交所原始文件）'
                and row.get('source_title')==HUBEI_ANNEX_TITLE and parts.fragment=='page=2'
                and period in ('2024','2025')
                and code in ('gov_fund_revenue','gov_fund_expenditure','debt_outstanding')
                and (code!='debt_outstanding' or period=='2025')
                and row.get('data_status')==('official_final' if period=='2024' else 'official_preliminary')
                and 'access_type=government_issuer_filing' in notes
                and 'raw_sha256='+HUBEI_ANNEX_SHA256 in notes
                and 'unit_evidence=explicit_source_heading' in notes)
    pages = {'general_budget_revenue':7, 'general_budget_expenditure':7,
             'gov_fund_revenue':7, 'gov_fund_expenditure':7,
             'land_transfer_revenue':8, 'debt_outstanding':8,
             'general_debt_outstanding':8}
    page = pages.get(row.get('indicator_code'))
    expected_status = 'official_preliminary' if period == '2025' else 'official_final'
    notes = row.get('parser_notes', '')
    return (base == SHAANXI_ISSUER_URL and period in ('2023', '2024', '2025')
            and row.get('region_code') == '610000' and row.get('region_name') == '陕西'
            and row.get('source_name') == '陕西省财政厅（上交所政府债券发行人原始披露）'
            and row.get('source_title') == SHAANXI_ISSUER_TITLE
            and page is not None and parts.fragment == 'page=' + str(page)
            and row.get('data_status') == expected_status
            and 'access_type=government_issuer_filing' in notes
            and 'raw_sha256=' + SHAANXI_ISSUER_SHA256 in notes
            and 'unit_overlap_verified=4' in notes
            and (period == '2025' or row.get('indicator_code') not in
                 ('debt_outstanding', 'general_debt_outstanding')))
