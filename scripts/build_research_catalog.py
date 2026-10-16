# -*- coding: utf-8 -*-
"""Generate ``data/research_catalog.json`` for the Business Research workspace.

Run from the project root::

    python scripts/build_research_catalog.py

The catalog is a *curated scaffold*: it exists so the workspace can navigate
between theories, constructs, methods, and the papers in the A* cache.  It is
not a literature review, and the generator enforces the rules that keep it
honest:

* ``tags`` hold only classifier tags that denote the entity.  Umbrella tags such
  as ``job_design``, ``survey``, or ``causal_inference`` go in ``broad_tags`` and
  are counted separately, so a narrow entity never claims its parent's volume.
  Tags were mined from the live ``astar_article_classifications`` vocabulary; a
  tag that the cache does not contain simply yields an honest zero.
* ``seminal_works`` carry author/year/title/venue written from domain knowledge
  and marked ``pending_verification``.  ``scripts/verify_research_sources.py``
  resolves them against OpenAlex or Crossref and upgrades only confident rows
  with source-specific metadata.  Nothing here invents a DOI or a citation
  count.
* Every cross-reference must resolve to an entity that exists; the build fails
  otherwise, because a dangling reference renders as a silently empty section.

Bilingual fields (``name_zh``, ``definition_zh``) exist so the page can show the
Chinese term next to the English one; the English text stays authoritative
because that is the language the source literature is written in.
"""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data' / 'research_catalog.json'
SOURCE_TEXT_CHAPTER_MAP = (
    ROOT / 'data' / 'research_source_text' /
    'management-organization-60-book-scan' / 'chapter_map.json'
)
sys.path.insert(0, str(Path(__file__).resolve().parent))

from research_catalog_constructs import CONSTRUCTS       # noqa: E402
from research_catalog_methods import METHODS             # noqa: E402
from research_catalog_expansion import (                 # noqa: E402
    BOOK60_EXISTING_IDS, BOOK60_SOURCE_PAGES, BOOK_THEORIES,
    DOMAIN_THEORIES, EXPANDED_CONSTRUCTS,
)
from research_catalog_sources import SOURCE_OVERRIDES, source_works_for  # noqa: E402
from research_catalog_deep_dives import DEEP_DIVES                      # noqa: E402
from research_catalog_deep_dives_strategy import STRATEGY_DIVES        # noqa: E402
from research_catalog_deep_dives_behavior import BEHAVIOR_DIVES        # noqa: E402
from research_catalog_deep_dives_constructs import CONSTRUCT_DIVES     # noqa: E402
from research_catalog_deep_dives_methods import METHOD_DIVES           # noqa: E402
from research_catalog_deep_dives_theories_b2 import THEORY_DIVES_B2    # noqa: E402
from research_catalog_deep_dives_constructs_b2 import CONSTRUCT_DIVES_B2  # noqa: E402
from research_catalog_deep_dives_methods_b2 import METHOD_DIVES_B2     # noqa: E402
from research_catalog_deep_dives_theories_b3 import THEORY_DIVES_B3    # noqa: E402
from research_catalog_deep_dives_constructs_b3 import CONSTRUCT_DIVES_B3  # noqa: E402
from research_catalog_deep_dives_methods_b3 import METHOD_DIVES_B3     # noqa: E402
from research_catalog_deep_dives_theories_b4 import THEORY_DIVES_B4    # noqa: E402
from research_catalog_deep_dives_constructs_b4 import CONSTRUCT_DIVES_B4  # noqa: E402
from research_catalog_deep_dives_constructs_b5 import CONSTRUCT_DIVES_B5  # noqa: E402
from research_catalog_deep_dives_constructs_b6 import CONSTRUCT_DIVES_B6  # noqa: E402
from research_catalog_deep_dives_constructs_b7 import CONSTRUCT_DIVES_B7  # noqa: E402
from research_catalog_deep_dives_constructs_b8 import CONSTRUCT_DIVES_B8  # noqa: E402
from research_catalog_deep_dives_constructs_b9 import CONSTRUCT_DIVES_B9  # noqa: E402
from research_catalog_deep_dives_constructs_b10 import CONSTRUCT_DIVES_B10  # noqa: E402
from research_catalog_deep_dives_methods_b4 import METHOD_DIVES_B4     # noqa: E402
from research_catalog_deep_dives_methods_b5 import METHOD_DIVES_B5     # noqa: E402
from research_catalog_deep_dives_theories_b5 import THEORY_DIVES_B5    # noqa: E402
from research_catalog_deep_dives_theories_b6 import THEORY_DIVES_B6    # noqa: E402
from research_catalog_deep_dives_theories_b7 import THEORY_DIVES_B7    # noqa: E402
from research_catalog_deep_dives_theories_b8 import THEORY_DIVES_B8    # noqa: E402
from research_catalog_deep_dives_theories_b9 import THEORY_DIVES_B9    # noqa: E402
from research_catalog_deep_dives_theories_b10 import THEORY_DIVES_B10   # noqa: E402
from research_catalog_deep_dives_theories_b11 import THEORY_DIVES_B11   # noqa: E402
from research_catalog_deep_dives_theories_b12 import THEORY_DIVES_B12   # noqa: E402
from research_catalog_deep_dives_theories_b13 import THEORY_DIVES_B13   # noqa: E402
from research_catalog_deep_dives_theories_b14 import THEORY_DIVES_B14   # noqa: E402
from research_catalog_deep_dives_theories_b15 import THEORY_DIVES_B15   # noqa: E402
from research_catalog_deep_dives_theories_b16 import THEORY_DIVES_B16   # noqa: E402
from research_catalog_disciplines import apply_disciplines      # noqa: E402

# Batches are separate modules only for file size; they merge into one map per
# entity kind. Adding a batch is one import and one entry here.
DEEP_DIVES = dict(DEEP_DIVES, **STRATEGY_DIVES, **BEHAVIOR_DIVES,
                  **THEORY_DIVES_B2, **THEORY_DIVES_B3, **THEORY_DIVES_B4,
                  **THEORY_DIVES_B5, **THEORY_DIVES_B6, **THEORY_DIVES_B7,
                  **THEORY_DIVES_B8, **THEORY_DIVES_B9, **THEORY_DIVES_B10,
                  **THEORY_DIVES_B11, **THEORY_DIVES_B12, **THEORY_DIVES_B13,
                  **THEORY_DIVES_B14, **THEORY_DIVES_B15,
                  **THEORY_DIVES_B16)
CONSTRUCT_DIVES = dict(CONSTRUCT_DIVES, **CONSTRUCT_DIVES_B2, **CONSTRUCT_DIVES_B3,
                       **CONSTRUCT_DIVES_B4, **CONSTRUCT_DIVES_B5,
                       **CONSTRUCT_DIVES_B6, **CONSTRUCT_DIVES_B7,
                       **CONSTRUCT_DIVES_B8, **CONSTRUCT_DIVES_B9,
                       **CONSTRUCT_DIVES_B10)
METHOD_DIVES = dict(METHOD_DIVES, **METHOD_DIVES_B2, **METHOD_DIVES_B3,
                    **METHOD_DIVES_B4, **METHOD_DIVES_B5)

# Keep the original source modules readable and append the expansion packs
# before the single reference-integrity check at the end of this file.
CONSTRUCTS += EXPANDED_CONSTRUCTS

SCAFFOLD = 'curated_scaffold'
PENDING = 'pending_verification'


def _load_book_source_text_map():
    """Load safe OCR locators when the user's local derived text layer exists.

    The catalog records status and page locators only.  It never embeds OCR
    text or the private absolute path to the derived reading aid.
    """
    if not SOURCE_TEXT_CHAPTER_MAP.exists():
        return {}
    try:
        payload = json.loads(SOURCE_TEXT_CHAPTER_MAP.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    result = {}
    for row in payload.get('chapters', []):
        if not isinstance(row, dict) or not row.get('theory_id'):
            continue
        result[row['theory_id']] = {
            'source_pack': payload.get('source_pack'),
            'status': 'ocr_derived_available',
            'chapter_locator_status': row.get('status'),
            'ocr_title_match': row.get('ocr_title_match') or {},
            'printed_page_start': row.get('printed_page_start'),
            'printed_page_end': row.get('printed_page_end'),
            'pdf_page_start': row.get('pdf_page_start'),
            'pdf_page_end': row.get('pdf_page_end'),
            'page_offset': row.get('page_offset'),
            'pdf_page_count': payload.get('pdf_page_count'),
            'human_review_required': True,
            'boundary_note': (
                'OCR is a derived local reading layer. Verify every definition, '
                'claim, measurement, and citation against the original scan before '
                'using it as evidence.'
            ),
        }
    return result


def W(authors, year, title, venue, kind='origin'):
    """A seminal work reference, unverified until the OpenAlex pass runs."""
    return {
        'authors': authors, 'year': year, 'title': title, 'venue': venue,
        'kind': kind, 'doi': None, 'openalex_id': None, 'cited_by_count': None,
        'verification': PENDING,
    }


def T(id, name, name_zh, abbreviation, disc, year, en, zh, tags=(), broad=(),
      kw=(), core=(), ante=(), mech=(), out=(), mod=(), bc=(), crit=(),
      apps=(), rel=(), works=(), model=None):
    entity = {
        'id': id, 'name': name, 'name_zh': name_zh, 'abbreviation': abbreviation,
        'definition': en, 'definition_zh': zh,
        'discipline': list(disc), 'origin_year': year,
        'tags': list(tags), 'broad_tags': list(broad), 'keywords': list(kw),
        'core_constructs': list(core), 'antecedents': list(ante),
        'mechanisms': list(mech), 'outcomes': list(out), 'moderators': list(mod),
        'boundary_conditions': list(bc), 'criticisms': list(crit),
        'applications': list(apps), 'related_theories': list(rel),
        'seminal_works': list(works), 'key_scholars': [],
        'source_status': SCAFFOLD,
    }
    if model:
        entity['conceptual_model'] = model
    return entity


# ─────────────────────────────────────────────────────────────────────────────
# Theories — OB / HR
# ─────────────────────────────────────────────────────────────────────────────

THEORIES = [
    T('job-demands-resources', 'Job Demands–Resources Theory', '工作要求—资源理论', 'JD-R',
      ['OB / HR', 'Management / Strategy'], 2001,
      'Job characteristics can be organized as demands that consume energy and resources that help people meet demands, with different pathways to strain, engagement, and performance.',
      '工作特征可分为消耗心理能量的"工作要求"与帮助应对要求的"工作资源"，两者通过健康损耗与动机激发两条不同路径影响倦怠、投入与绩效。',
      tags=['jd_r', 'job demands-resources'], broad=['job_design'],
      kw=['job demands', 'job resources', 'burnout', 'engagement', 'exhaustion', 'autonomy'],
      core=['workload', 'autonomy', 'employee-engagement', 'burnout', 'social-support'],
      ante=['workload', 'algorithmic-monitoring', 'social-support'],
      mech=['resource depletion', 'motivational process', 'exhaustion', 'engagement'],
      out=['burnout', 'employee-engagement', 'employee-voice', 'job-satisfaction'],
      mod=['social-support', 'autonomy'],
      bc=['The demand/resource classification depends on context; the same job feature may be experienced differently across workers and settings.',
          'Resource gains and losses may unfold over time rather than in a single cross-sectional observation.'],
      crit=['Many applications use cross-sectional self-report data that cannot establish temporal process or causality.',
            'Demand and resource labels can become broad catch-alls unless the mechanism and measurement are specified.'],
      apps=['Remote Work', 'Algorithmic Management', 'Employee Engagement', 'Healthcare', 'Teams'],
      rel=['conservation-of-resources', 'self-determination-theory', 'job-characteristics-model'],
      works=[W('Demerouti, Bakker, Nachreiner & Schaufeli', 2001, 'The job demands-resources model of burnout', 'Journal of Applied Psychology'),
             W('Bakker & Demerouti', 2017, 'Job demands-resources theory: Taking stock and looking forward', 'Journal of Occupational Health Psychology', 'major_review')],
      model={'note': 'Dual-pathway scaffold. Verify the specific mechanism and measurement against primary sources before using it in a manuscript.',
             'pathways': [{'label': 'Health impairment pathway', 'steps': ['workload', 'burnout', 'turnover-intention']},
                          {'label': 'Motivational pathway', 'steps': ['autonomy', 'employee-engagement', 'job-satisfaction']}]}),

    T('conservation-of-resources', 'Conservation of Resources Theory', '资源保存理论', 'COR',
      ['OB / HR', 'Management / Strategy'], 1989,
      'People strive to obtain, retain, and protect valued resources; stress arises from resource loss, threatened loss, or failure to gain after investment.',
      '人们努力获取、保有并保护有价值的资源；压力源于资源损失、资源受到威胁，或投入资源后未能获得预期回报。',
      tags=['conservation_of_resources'],
      kw=['resource loss', 'resource gain', 'stress', 'depletion', 'recovery'],
      core=['burnout', 'social-support', 'autonomy', 'workload', 'job-insecurity'],
      ante=['workload', 'job-insecurity', 'algorithmic-monitoring'],
      mech=['resource loss spiral', 'resource investment', 'gain spiral'],
      out=['burnout', 'turnover-intention', 'employee-engagement'],
      mod=['social-support', 'autonomy'],
      bc=['Resource value is partly subjective and context dependent, so the same loss is not equivalent across people.',
          'Loss spirals are proposed to accelerate over time, which single-wave designs cannot observe.'],
      crit=['The resource definition is broad, and resource lists vary across studies, making comparison difficult.',
            'Loss primacy and spiral claims require longitudinal designs that many applications do not use.'],
      apps=['Burnout', 'Remote Work', 'Job Insecurity', 'Healthcare'],
      rel=['job-demands-resources', 'social-exchange-theory'],
      works=[W('Hobfoll', 1989, 'Conservation of resources: A new attempt at conceptualizing stress', 'American Psychologist'),
             W('Halbesleben, Neveu, Paustian-Underdahl & Westman', 2014, 'Getting to the "COR": Understanding the role of resources in conservation of resources theory', 'Journal of Management', 'major_review')]),

    T('social-exchange-theory', 'Social Exchange Theory', '社会交换理论', 'SET',
      ['OB / HR', 'Management / Strategy', 'Marketing'], 1964,
      'Relationships are shaped by reciprocal exchanges of valued resources, perceived obligations, trust, and fairness.',
      '关系由有价值资源的互惠交换、感知义务、信任与公平所塑造；一方的付出会引发另一方回报的义务感。',
      tags=['social_exchange', 'social exchange theory'],
      kw=['reciprocity', 'exchange', 'obligation', 'trust', 'support', 'fairness'],
      core=['social-support', 'trust', 'employee-voice', 'job-satisfaction', 'perceived-organizational-support'],
      ante=['social-support', 'leader-support', 'perceived-organizational-support'],
      mech=['reciprocity', 'felt obligation', 'trust development'],
      out=['employee-voice', 'employee-engagement', 'job-satisfaction', 'turnover-intention'],
      mod=['trust'],
      bc=['Exchange norms differ across cultures and employment relationships; reciprocity is not universally symmetric.',
          'The theory describes an exchange logic rather than predicting which resource matters most in a given setting.'],
      crit=['The framework is broad enough to post-hoc rationalize many correlations, which weakens its falsifiability.',
            'Perceived obligation and reciprocity are often measured with overlapping items, risking construct redundancy.'],
      apps=['Leadership', 'Employee Voice', 'Teams', 'Buyer–Supplier Relationships'],
      rel=['conservation-of-resources', 'job-demands-resources', 'organizational-support-theory', 'leader-member-exchange'],
      works=[W('Blau', 1964, 'Exchange and Power in Social Life', 'Wiley'),
             W('Cropanzano & Mitchell', 2005, 'Social exchange theory: An interdisciplinary review', 'Journal of Management', 'major_review')]),

    T('self-determination-theory', 'Self-Determination Theory', '自我决定理论', 'SDT',
      ['OB / HR', 'Management / Strategy', 'Marketing'], 1985,
      'Motivation quality depends on the satisfaction of basic psychological needs for autonomy, competence, and relatedness.',
      '动机的质量取决于自主、胜任与关系三种基本心理需要是否得到满足；满足程度决定动机是自主的还是受控的。',
      tags=['self_determination'],
      kw=['autonomy', 'competence', 'relatedness', 'intrinsic motivation', 'need satisfaction'],
      core=['autonomy', 'employee-engagement', 'job-satisfaction', 'social-support'],
      ante=['autonomy', 'leader-support', 'social-support'],
      mech=['need satisfaction', 'internalization', 'autonomous motivation'],
      out=['employee-engagement', 'job-satisfaction', 'employee-voice'],
      mod=['leader-support'],
      bc=['Need satisfaction is theorized as universal, but its expression and measurement vary across cultural settings.',
          'Controlled and autonomous motivation can coexist rather than sitting on a single continuum in practice.'],
      crit=['Self-report need-satisfaction measures overlap conceptually with the outcomes they are used to predict.',
            'The universality claim remains contested in cross-cultural work.'],
      apps=['Employee Engagement', 'Algorithmic Management', 'Remote Work', 'Education'],
      rel=['job-characteristics-model', 'job-demands-resources'],
      works=[W('Deci & Ryan', 1985, 'Intrinsic Motivation and Self-Determination in Human Behavior', 'Plenum'),
             W('Ryan & Deci', 2000, 'Self-determination theory and the facilitation of intrinsic motivation, social development, and well-being', 'American Psychologist')]),

    T('job-characteristics-model', 'Job Characteristics Model', '工作特征模型', 'JCM',
      ['OB / HR'], 1976,
      'Five core job characteristics influence critical psychological states, which in turn shape motivation, satisfaction, and performance.',
      '技能多样性、任务完整性、任务重要性、自主性与反馈五个核心工作特征，通过三种关键心理状态影响动机、满意度与绩效。',
      broad=['job_design'],
      kw=['skill variety', 'task identity', 'task significance', 'autonomy', 'feedback'],
      core=['autonomy', 'job-satisfaction', 'employee-engagement'],
      ante=['autonomy', 'workload'],
      mech=['experienced meaningfulness', 'experienced responsibility', 'knowledge of results'],
      out=['job-satisfaction', 'employee-engagement'],
      mod=['growth need strength'],
      bc=['Growth need strength was proposed as a moderator, and its support has been inconsistent across studies.',
          'The model was developed for individual jobs and extends imperfectly to team or platform-mediated work.'],
      crit=['Meta-analytic support for the mediating psychological states is weaker than for the direct characteristic–outcome links.',
            'The instrument and the outcomes are usually collected in one survey wave, inflating observed relationships.'],
      apps=['Job Design', 'Remote Work', 'Algorithmic Management'],
      rel=['job-demands-resources', 'self-determination-theory'],
      works=[W('Hackman & Oldham', 1976, 'Motivation through the design of work: Test of a theory', 'Organizational Behavior and Human Performance')]),

    T('leader-member-exchange', 'Leader–Member Exchange Theory', '领导—成员交换理论', 'LMX',
      ['OB / HR'], 1975,
      'Leaders form exchange relationships of differing quality with individual followers, and that relationship quality predicts follower attitudes and behaviour.',
      '领导与每个下属分别形成质量不同的交换关系，关系质量（而非统一的领导风格）预测下属的态度与行为。',
      tags=['leader-member exchange', 'lmx'],
      kw=['lmx', 'leader-member exchange', 'dyadic relationship', 'in-group', 'supervisor'],
      core=['leader-support', 'trust', 'employee-voice', 'job-satisfaction'],
      ante=['leader-support', 'trust'],
      mech=['role-making', 'reciprocal exchange', 'differentiated treatment'],
      out=['employee-voice', 'job-satisfaction', 'turnover-intention', 'employee-engagement'],
      mod=['psychological-safety'],
      bc=['Differentiation within a team can help or harm depending on whether members see it as fair.',
          'Most evidence comes from follower-rated LMX, which does not always agree with leader-rated LMX.'],
      crit=['Leader and follower reports of the same relationship correlate only modestly, questioning what is being measured.',
            'The construct overlaps heavily with perceived supervisor support and trust in the leader.'],
      apps=['Leadership', 'Employee Voice', 'Teams', 'Remote Work'],
      rel=['social-exchange-theory', 'organizational-support-theory'],
      works=[W('Dansereau, Graen & Haga', 1975, 'A vertical dyad linkage approach to leadership within formal organizations', 'Organizational Behavior and Human Performance'),
             W('Graen & Uhl-Bien', 1995, 'Relationship-based approach to leadership: Development of LMX theory over 25 years', 'The Leadership Quarterly', 'major_review')]),

    T('organizational-support-theory', 'Organizational Support Theory', '组织支持理论', 'OST',
      ['OB / HR'], 1986,
      'Employees form a global belief about how far the organization values their contributions and cares about their wellbeing, and reciprocate that belief.',
      '员工会形成"组织在多大程度上重视我的贡献、关心我的福祉"的总体信念，并据此以态度和行为回报组织。',
      tags=['organizational support theory', 'perceived organizational support'],
      kw=['perceived organizational support', 'organizational support', 'felt obligation'],
      core=['perceived-organizational-support', 'leader-support', 'employee-engagement', 'turnover-intention'],
      ante=['leader-support', 'social-support'],
      mech=['felt obligation', 'socioemotional needs', 'reciprocity'],
      out=['employee-engagement', 'turnover-intention', 'job-satisfaction', 'employee-voice'],
      bc=['Support attributed to discretionary organizational choice matters more than support seen as legally mandated.',
          'The construct is organization-directed; supervisor support operates through a partly separate path.'],
      crit=['Perceived organizational support and affective commitment are empirically hard to separate.',
            'Nearly all evidence is single-source self-report collected at one time point.'],
      apps=['Employee Engagement', 'Turnover', 'Remote Work', 'Healthcare'],
      rel=['social-exchange-theory', 'leader-member-exchange'],
      works=[W('Eisenberger, Huntington, Hutchison & Sowa', 1986, 'Perceived organizational support', 'Journal of Applied Psychology'),
             W('Kurtessis, Eisenberger, Ford, Buffardi, Stewart & Adis', 2017, 'Perceived organizational support: A meta-analytic evaluation of organizational support theory', 'Journal of Management', 'major_review')]),

    T('psychological-contract-theory', 'Psychological Contract Theory', '心理契约理论', None,
      ['OB / HR'], 1989,
      'Employees hold beliefs about the reciprocal obligations between themselves and the employer; perceived breach of those beliefs drives strong reactions.',
      '员工对自己与雇主之间互惠义务持有一套主观信念；当感知到这些信念被违背时，会引发强烈的态度与行为反应。',
      tags=['psychological contract', 'psychological contract theory'],
      kw=['psychological contract', 'breach', 'violation', 'obligations', 'employment relationship'],
      core=['trust', 'turnover-intention', 'employee-voice', 'job-satisfaction'],
      ante=['leader-support', 'perceived-organizational-support'],
      mech=['perceived breach', 'felt violation', 'reciprocity adjustment'],
      out=['turnover-intention', 'employee-voice', 'trust', 'job-satisfaction'],
      bc=['The contract is subjective and idiosyncratic, so two employees under the same policy may hold different contracts.',
          'Breach effects depend on attributions about whether the employer could have acted otherwise.'],
      crit=['Breach and violation are often measured together, blurring the cognitive and affective components.',
            'Retrospective measurement makes it hard to separate breach perception from its consequences.'],
      apps=['Return-to-Office', 'Gig Work', 'Restructuring', 'Remote Work'],
      rel=['social-exchange-theory', 'organizational-support-theory'],
      works=[W('Rousseau', 1989, 'Psychological and implied contracts in organizations', 'Employee Responsibilities and Rights Journal'),
             W('Zhao, Wayne, Glibkowski & Bravo', 2007, 'The impact of psychological contract breach on work-related outcomes: A meta-analysis', 'Personnel Psychology', 'major_review')]),

    T('social-identity-theory', 'Social Identity Theory', '社会认同理论', 'SIT',
      ['OB / HR', 'Marketing', 'Management / Strategy'], 1979,
      'People derive part of their self-concept from group memberships, favouring the in-group and differentiating it from out-groups.',
      '个体的自我概念部分来自群体成员身份，因而倾向于偏袒内群体并与外群体作出区分。',
      tags=['social identity theory', 'identity theory', 'self-categorization theory', 'social categorization theory'],
      kw=['social identity', 'in-group', 'out-group', 'identification', 'categorization'],
      core=['trust', 'employee-engagement', 'psychological-safety'],
      ante=['social-support', 'leader-support'],
      mech=['categorization', 'identification', 'social comparison'],
      out=['employee-engagement', 'employee-voice', 'turnover-intention'],
      bc=['Identity salience is situational; a group identity that predicts behaviour in one context may be irrelevant in another.',
          'Multiple identities can conflict, so a single identification measure can be misleading.'],
      crit=['Organizational identification is often measured with items that overlap affective commitment.',
            'Laboratory minimal-group findings transfer imperfectly to enduring workplace groups.'],
      apps=['Teams', 'Diversity', 'Brand Communities', 'Mergers'],
      rel=['social-exchange-theory', 'social-cognitive-theory'],
      works=[W('Tajfel & Turner', 1979, 'An integrative theory of intergroup conflict', 'The Social Psychology of Intergroup Relations'),
             W('Ashforth & Mael', 1989, 'Social identity theory and the organization', 'Academy of Management Review')]),

    T('attachment-theory', 'Attachment Theory', '依恋理论', None,
      ['OB / HR', 'Marketing', 'Management / Strategy'], 1969,
      'A behavioural system regulates proximity to figures who serve as a safe haven under threat and a secure base for exploration, and repeated experience of their availability forms working models that shape later relationships.',
      '依恋行为系统调节个体与依恋对象之间的接近程度——该对象在威胁下充当安全港、在探索时充当安全基地；关于其可得性的反复经验形成内部工作模型，塑造日后的各种关系。',
      tags=['attachment theory', 'attachment style', 'adult attachment', 'brand attachment'],
      kw=['attachment', 'secure base', 'safe haven', 'attachment anxiety', 'attachment avoidance'],
      core=['trust', 'belongingness', 'affective-commitment'],
      ante=['social-support', 'leader-support'],
      mech=['proximity seeking', 'internal working model', 'safe haven', 'secure base'],
      out=['affective-commitment', 'turnover-intention', 'customer-loyalty', 'brand-equity'],
      mod=['psychological-safety'],
      bc=['The theory assumes a figure who can respond and be sought out under threat; a brand cannot, so predictions about separation and protection transfer uncertainly.',
          'Attachment style is measured for close relationships and applied to workplace and consumption targets it was not validated on.'],
      crit=['Anxiety and avoidance are frequently collapsed into a secure/insecure split, which discards the distinction that carries the prediction.',
            'The internal working model is never observed directly in business research and is inferred from the self-report it explains.'],
      apps=['Leadership', 'Brand Relationships', 'Turnover', 'Consumer Loyalty'],
      rel=['social-exchange-theory', 'social-identity-theory', 'need-to-belong-theory',
           'organizational-support-theory', 'leader-member-exchange'],
      works=[W('Bowlby', 1969, 'Attachment and Loss, Volume 1: Attachment', 'Basic Books'),
             W('Hazan & Shaver', 1987, 'Romantic love conceptualized as an attachment process',
               'Journal of Personality and Social Psychology', kind='extension'),
             W('Thomson, MacInnis & Park', 2005,
               "The ties that bind: Measuring the strength of consumers' emotional attachments to brands",
               'Journal of Consumer Psychology', kind='extension')]),

    T('social-cognitive-theory', 'Social Cognitive Theory', '社会认知理论', 'SCT',
      ['OB / HR', 'Information Systems', 'Marketing'], 1986,
      'Behaviour, personal factors, and the environment reciprocally determine each other, with self-efficacy central to what people attempt and persist at.',
      '行为、个人因素与环境三者交互决定；其中自我效能感决定人们愿意尝试什么、以及在困难面前能坚持多久。',
      tags=['social cognitive theory', 'social learning theory', 'self-efficacy'],
      kw=['self-efficacy', 'observational learning', 'reciprocal determinism', 'modelling'],
      core=['employee-engagement', 'psychological-safety', 'autonomy'],
      ante=['leader-support', 'social-support'],
      mech=['self-efficacy', 'vicarious learning', 'outcome expectancy'],
      out=['employee-engagement', 'employee-voice', 'technology-adoption-intention'],
      bc=['Self-efficacy is domain specific; a general measure predicts poorly for a specific task.',
          'Reciprocal determinism is difficult to test without designs that observe all three elements over time.'],
      crit=['Self-efficacy and past performance are strongly confounded in cross-sectional designs.',
            'The breadth of the framework makes decisive disconfirmation difficult.'],
      apps=['Training', 'Technology Adoption', 'Sales Performance'],
      rel=['self-determination-theory', 'technology-acceptance-model'],
      works=[W('Bandura', 1986, 'Social Foundations of Thought and Action: A Social Cognitive Theory', 'Prentice-Hall'),
             W('Bandura', 1977, 'Self-efficacy: Toward a unifying theory of behavioral change', 'Psychological Review')]),

    T('goal-setting-theory', 'Goal-Setting Theory', '目标设定理论', None,
      ['OB / HR'], 1990,
      'Specific and difficult goals produce higher performance than vague or easy goals, provided the person is committed and has the ability and feedback needed.',
      '在个体具备能力、承诺与反馈的前提下，具体且有难度的目标比模糊或容易的目标带来更高绩效。',
      tags=['goal setting theory', 'goal-setting theory'],
      kw=['goal difficulty', 'goal specificity', 'goal commitment', 'feedback'],
      core=['employee-engagement', 'autonomy', 'workload'],
      ante=['leader-support', 'autonomy'],
      mech=['effort direction', 'persistence', 'strategy development'],
      out=['employee-engagement', 'job-satisfaction', 'burnout'],
      mod=['autonomy', 'leader-support'],
      bc=['Difficult goals help on straightforward tasks but can impair performance on novel or complex learning tasks.',
          'Goal effects require feedback; without it, difficulty does not translate into performance.'],
      crit=['Aggressive goal setting has documented side effects including narrowed focus and unethical behaviour.',
            'Much of the foundational evidence is from short laboratory tasks rather than sustained work.'],
      apps=['Performance Management', 'Algorithmic Management', 'Sales'],
      rel=['self-determination-theory', 'expectancy-theory'],
      works=[W('Locke & Latham', 1990, 'A Theory of Goal Setting and Task Performance', 'Prentice-Hall'),
             W('Locke & Latham', 2002, 'Building a practically useful theory of goal setting and task motivation', 'American Psychologist', 'major_review')]),

    T('organizational-justice-theory', 'Organizational Justice Theory', '组织公平理论', None,
      ['OB / HR'], 1987,
      'Employees evaluate the fairness of outcomes, procedures, interpersonal treatment, and information, and these judgements shape their attitudes and behaviour.',
      '员工会分别评价结果分配、决策程序、人际对待与信息说明是否公平，这些判断进而塑造其态度与行为。',
      tags=['justice theory', 'organizational justice', 'equity theory'],
      kw=['distributive justice', 'procedural justice', 'interactional justice', 'fairness'],
      core=['trust', 'employee-voice', 'turnover-intention', 'job-satisfaction'],
      ante=['leader-support', 'algorithmic-transparency'],
      mech=['fairness heuristic', 'uncertainty reduction', 'reciprocity'],
      out=['employee-voice', 'trust', 'turnover-intention', 'job-satisfaction'],
      bc=['Justice dimensions substitute for one another: procedural fairness matters most when outcomes are unfavourable.',
          'Fairness standards are culturally and institutionally shaped rather than universal.'],
      crit=['The four dimensions are highly correlated, and their discriminant validity is repeatedly questioned.',
            'Most evidence is cross-sectional perception data collected alongside the outcomes.'],
      apps=['Algorithmic Management', 'Performance Appraisal', 'Layoffs', 'Pay Transparency'],
      rel=['social-exchange-theory', 'organizational-support-theory'],
      works=[W('Greenberg', 1987, 'A taxonomy of organizational justice theories', 'Academy of Management Review'),
             W('Colquitt, Conlon, Wesson, Porter & Ng', 2001, 'Justice at the millennium: A meta-analytic review of 25 years of organizational justice research', 'Journal of Applied Psychology', 'major_review')]),

    T('affective-events-theory', 'Affective Events Theory', '情感事件理论', 'AET',
      ['OB / HR'], 1996,
      'Features of the work environment generate discrete affective events, and the emotional reactions to those events drive attitudes and behaviour over time.',
      '工作环境特征会引发一系列具体的情感事件，对这些事件的情绪反应随时间累积，进而驱动工作态度与行为。',
      tags=['affective events theory'],
      kw=['affect', 'emotion', 'events', 'mood', 'affective reactions'],
      core=['job-satisfaction', 'burnout', 'employee-engagement'],
      ante=['workload', 'leader-support', 'algorithmic-monitoring'],
      mech=['affective reaction', 'affect-driven behaviour', 'judgement-driven behaviour'],
      out=['job-satisfaction', 'burnout', 'turnover-intention'],
      bc=['The theory is explicitly within-person and over time; between-person designs cannot test its core claim.',
          'Event salience varies by individual disposition.'],
      crit=['Testing it properly needs experience sampling, which many applications substitute with recall measures.',
            'The distinction between affect-driven and judgement-driven behaviour is hard to operationalize cleanly.'],
      apps=['Employee Wellbeing', 'Service Work', 'Remote Work'],
      rel=['job-demands-resources', 'conservation-of-resources'],
      works=[W('Weiss & Cropanzano', 1996, 'Affective events theory: A theoretical discussion of the structure, causes and consequences of affective experiences at work', 'Research in Organizational Behavior')]),

    T('expectancy-theory', 'Expectancy Theory', '期望理论', 'VIE',
      ['OB / HR', 'Management / Strategy'], 1964,
      'Motivation is a function of the expectancy that effort produces performance, the instrumentality of performance for outcomes, and the valence of those outcomes.',
      '动机取决于三者的乘积：努力能带来绩效的期望、绩效能换来结果的工具性，以及个体对该结果的效价。',
      tags=['expectancy theory'],
      kw=['expectancy', 'instrumentality', 'valence', 'effort', 'motivation'],
      core=['employee-engagement', 'job-satisfaction'],
      ante=['leader-support', 'autonomy'],
      mech=['expectancy', 'instrumentality', 'valence'],
      out=['employee-engagement', 'job-satisfaction'],
      bc=['The multiplicative form assumes people compute trade-offs deliberately, which fits considered choices better than habitual behaviour.',
          'It is a within-person model of choice among alternatives, often tested between persons.'],
      crit=['The multiplicative specification is rarely tested as specified; most studies use additive proxies.',
            'Component measures are frequently collected in the same survey as the outcome.'],
      apps=['Compensation Design', 'Sales', 'Performance Management'],
      rel=['goal-setting-theory', 'self-determination-theory'],
      works=[W('Vroom', 1964, 'Work and Motivation', 'Wiley')]),

    T('job-embeddedness-theory', 'Job Embeddedness Theory', '工作嵌入理论', None,
      ['OB / HR'], 2001,
      'People stay in jobs because of links, fit, and the sacrifice leaving would entail, on and off the job — not only because of satisfaction.',
      '员工留任不只因为满意度，还因为与人和组织的联结、与环境的匹配，以及离职将付出的牺牲，工作内外皆然。',
      tags=['job embeddedness', 'embeddedness'],
      kw=['embeddedness', 'links', 'fit', 'sacrifice', 'retention'],
      core=['turnover-intention', 'social-support', 'job-satisfaction'],
      ante=['social-support', 'leader-support'],
      mech=['links', 'fit', 'sacrifice'],
      out=['turnover-intention'],
      bc=['Off-the-job embeddedness matters more where relocation is costly; remote work weakens that mechanism.',
          'Embeddedness can retain low performers as readily as high performers.'],
      crit=['The composite measure mixes conceptually distinct components, complicating interpretation.',
            'Incremental variance over satisfaction and commitment is modest in several replications.'],
      apps=['Turnover', 'Remote Work', 'Healthcare Staffing'],
      rel=['social-exchange-theory', 'conservation-of-resources'],
      works=[W('Mitchell, Holtom, Lee, Sablynski & Erez', 2001, 'Why people stay: Using job embeddedness to predict voluntary turnover', 'Academy of Management Journal')]),

    T('person-environment-fit', 'Person–Environment Fit Theory', '个人—环境匹配理论', 'P–E Fit',
      ['OB / HR'], 1987,
      'Attitudes and behaviour depend on the compatibility between a person and their work environment, including the job, group, supervisor, and organization.',
      '态度与行为取决于个体与其工作环境（岗位、团队、主管、组织）之间的契合程度，而非单独由任一方决定。',
      tags=['person-environment fit', 'person-organization fit', 'person-job fit'],
      kw=['fit', 'congruence', 'person-organization fit', 'person-job fit', 'values'],
      core=['job-satisfaction', 'turnover-intention', 'employee-engagement'],
      ante=['autonomy', 'social-support'],
      mech=['needs-supplies fit', 'demands-abilities fit', 'value congruence'],
      out=['job-satisfaction', 'turnover-intention', 'employee-engagement'],
      bc=['Different fit types predict different outcomes; a single global fit measure obscures this.',
          'Fit perceptions and objective correspondence often diverge.'],
      crit=['Difference-score and polynomial approaches yield different conclusions from the same data.',
            'Perceived fit is measured close in time and content to the outcomes it predicts.'],
      apps=['Recruitment', 'Onboarding', 'Remote Work'],
      rel=['job-characteristics-model', 'self-determination-theory'],
      works=[W('Edwards', 1991, 'Person-job fit: A conceptual integration, literature review, and methodological critique', 'International Review of Industrial and Organizational Psychology'),
             W('Kristof-Brown, Zimmerman & Johnson', 2005, 'Consequences of individuals’ fit at work: A meta-analysis', 'Personnel Psychology', 'major_review')]),

    T('human-capital-theory', 'Human Capital Theory', '人力资本理论', None,
      ['OB / HR', 'Management / Strategy'], 1964,
      'Investment in education, training, and experience raises individual productivity and therefore earnings and firm value.',
      '教育、培训与经验方面的投资提升个体生产率，进而提高其收入水平与企业价值。',
      tags=['human capital theory', 'human capital'],
      kw=['human capital', 'training', 'education', 'skills', 'productivity'],
      core=['employee-engagement', 'turnover-intention'],
      ante=['leader-support'],
      mech=['skill accumulation', 'productivity gain', 'specificity of investment'],
      out=['turnover-intention', 'job-satisfaction'],
      bc=['Firm-specific and general human capital have opposite implications for who captures the returns.',
          'Returns depend on labour-market institutions and mobility.'],
      crit=['Ability and schooling are confounded, so estimated returns risk selection bias without a credible design.',
            'It treats skill as individually owned, understating team and organizational complementarities.'],
      apps=['Labor Market', 'Training', 'Inequality', 'AI and Skills'],
      rel=['resource-based-view', 'knowledge-based-view'],
      works=[W('Becker', 1964, 'Human Capital: A Theoretical and Empirical Analysis, with Special Reference to Education', 'University of Chicago Press')]),
]


# ─────────────────────────────────────────────────────────────────────────────
# Theories — Information Systems
# ─────────────────────────────────────────────────────────────────────────────

THEORIES += [
    T('technology-acceptance-model', 'Technology Acceptance Model', '技术接受模型', 'TAM',
      ['Information Systems'], 1989,
      'Perceived usefulness and perceived ease of use shape attitude and behavioural intention, which in turn predict system use.',
      '感知有用性与感知易用性影响使用态度和行为意向，行为意向进而预测实际的系统使用。',
      tags=['technology acceptance model'],
      kw=['perceived usefulness', 'perceived ease of use', 'behavioural intention', 'adoption'],
      core=['trust', 'technology-adoption-intention'],
      ante=['algorithmic-transparency'],
      mech=['attitude formation', 'intention formation'],
      out=['technology-adoption-intention'],
      bc=['The model was developed for voluntary individual adoption of workplace systems and transfers imperfectly to mandated or collective use.',
          'Self-reported use is a weak proxy for observed use.'],
      crit=['The model is often criticized for parsimony that omits social, organizational, and habit factors.',
            'Repeated replication with new moderators has been argued to add limited theoretical value.'],
      apps=['Enterprise Systems', 'Mobile Apps', 'AI Assistants'],
      rel=['utaut', 'expectation-confirmation-theory', 'social-cognitive-theory'],
      works=[W('Davis', 1989, 'Perceived usefulness, perceived ease of use, and user acceptance of information technology', 'MIS Quarterly'),
             W('Venkatesh & Davis', 2000, 'A theoretical extension of the technology acceptance model: Four longitudinal field studies', 'Management Science', 'major_extension')]),

    T('utaut', 'Unified Theory of Acceptance and Use of Technology', '整合型技术接受与使用理论', 'UTAUT',
      ['Information Systems'], 2003,
      'Performance expectancy, effort expectancy, social influence, and facilitating conditions predict behavioural intention and use, moderated by individual characteristics.',
      '绩效期望、努力期望、社会影响与便利条件共同预测行为意向与使用行为，并受年龄、性别、经验、自愿性等个体特征调节。',
      tags=['utaut', 'unified theory of acceptance and use of technology'],
      kw=['performance expectancy', 'effort expectancy', 'social influence', 'facilitating conditions'],
      core=['trust', 'technology-adoption-intention'],
      mech=['intention formation', 'facilitating conditions'],
      out=['technology-adoption-intention'],
      bc=['The original moderator set (age, gender, experience, voluntariness) is not always meaningful in every context.',
          'Explained variance is often reported from the same cross-sectional survey that measured the predictors.'],
      crit=['Adding constructs to raise explained variance has been criticized as incremental rather than theoretical progress.',
            'Common method variance is a recurring concern in single-survey applications.'],
      apps=['Enterprise Systems', 'Mobile Payment', 'AI Adoption'],
      rel=['technology-acceptance-model', 'diffusion-of-innovations'],
      works=[W('Venkatesh, Morris, Davis & Davis', 2003, 'User acceptance of information technology: Toward a unified view', 'MIS Quarterly'),
             W('Venkatesh, Thong & Xu', 2012, 'Consumer acceptance and use of information technology: Extending the unified theory of acceptance and use of technology', 'MIS Quarterly', 'major_extension')]),

    T('is-success-model', 'Information Systems Success Model', '信息系统成功模型', 'D&M',
      ['Information Systems'], 1992,
      'System, information, and service quality shape use and user satisfaction, which jointly produce net benefits.',
      '系统质量、信息质量与服务质量影响使用行为与用户满意度，二者共同产生净收益。',
      tags=['is success model', 'information systems success', 'delone and mclean'],
      kw=['system quality', 'information quality', 'service quality', 'user satisfaction', 'net benefits'],
      core=['trust', 'technology-adoption-intention', 'job-satisfaction'],
      mech=['quality perception', 'satisfaction', 'benefit realization'],
      out=['technology-adoption-intention', 'job-satisfaction'],
      bc=['Net benefits must be defined for a stated stakeholder and level of analysis before the model is testable.',
          'Use is a meaningful outcome only where use is voluntary.'],
      crit=['"Net benefits" is an open placeholder that different studies fill incompatibly.',
            'Quality dimensions are usually measured perceptually rather than objectively.'],
      apps=['Enterprise Systems', 'E-Government', 'Analytics Platforms'],
      rel=['technology-acceptance-model', 'expectation-confirmation-theory', 'task-technology-fit'],
      works=[W('DeLone & McLean', 1992, 'Information systems success: The quest for the dependent variable', 'Information Systems Research'),
             W('DeLone & McLean', 2003, 'The DeLone and McLean model of information systems success: A ten-year update', 'Journal of Management Information Systems', 'major_extension')]),

    T('task-technology-fit', 'Task–Technology Fit Theory', '任务—技术匹配理论', 'TTF',
      ['Information Systems'], 1995,
      'Technology improves performance only when its capabilities match the requirements of the task it supports.',
      '只有当技术的功能特性与其所支持任务的要求相匹配时，技术才能真正提升绩效。',
      tags=['task-technology fit'],
      kw=['task technology fit', 'fit', 'utilization', 'performance impact'],
      core=['technology-adoption-intention', 'autonomy'],
      mech=['fit assessment', 'utilization', 'performance impact'],
      out=['technology-adoption-intention', 'job-satisfaction'],
      bc=['Fit is defined relative to a specified task; a general fit score is not interpretable.',
          'It predicts performance impact better than adoption intention.'],
      crit=['Fit is operationalized inconsistently across studies (profile deviation, moderation, matching).',
            'Task characteristics are often self-reported by the same person rating performance.'],
      apps=['Analytics Tools', 'Mobile Work', 'AI Assistants'],
      rel=['technology-acceptance-model', 'is-success-model'],
      works=[W('Goodhue & Thompson', 1995, 'Task-technology fit and individual performance', 'MIS Quarterly')]),

    T('expectation-confirmation-theory', 'Expectation–Confirmation Theory', '期望确认理论', 'ECT',
      ['Information Systems', 'Marketing'], 2001,
      'Continued use depends on whether experience confirms prior expectations, which drives satisfaction and then continuance intention.',
      '持续使用取决于实际体验是否确认了先前的期望；确认程度决定满意度，满意度再决定继续使用意向。',
      tags=['expectation-confirmation theory', 'expectation confirmation model'],
      kw=['confirmation', 'satisfaction', 'continuance intention', 'post-adoption'],
      core=['job-satisfaction', 'technology-adoption-intention', 'trust'],
      mech=['confirmation', 'satisfaction', 'continuance'],
      out=['technology-adoption-intention', 'job-satisfaction'],
      bc=['It explains continuance rather than initial adoption; the two have different antecedents.',
          'Expectations must be measured before use for the confirmation logic to hold.'],
      crit=['Most studies measure expectation retrospectively, which contaminates the confirmation construct.',
            'Satisfaction and continuance intention are measured with adjacent items in one survey.'],
      apps=['SaaS Retention', 'Mobile Apps', 'AI Assistants'],
      rel=['technology-acceptance-model', 'is-success-model'],
      works=[W('Bhattacherjee', 2001, 'Understanding information systems continuance: An expectation-confirmation model', 'MIS Quarterly'),
             W('Oliver', 1980, 'A cognitive model of the antecedents and consequences of satisfaction decisions', 'Journal of Marketing Research', 'origin')]),

    T('media-richness-theory', 'Media Richness Theory', '媒介丰富性理论', 'MRT',
      ['Information Systems'], 1986,
      'Communication media differ in their capacity to carry cues and enable feedback; effective communication matches media richness to task equivocality.',
      '不同媒介传递线索与支持即时反馈的能力不同；有效沟通要求媒介的丰富性与任务的模糊程度相匹配。',
      tags=['media richness theory', 'media richness'],
      kw=['media richness', 'equivocality', 'cues', 'feedback', 'communication'],
      core=['trust', 'psychological-safety', 'social-support'],
      mech=['cue availability', 'feedback immediacy', 'equivocality reduction'],
      out=['trust', 'employee-voice'],
      bc=['Predictions weaken where users have long experience with a medium and adapt it to rich uses.',
          'It was developed before persistent, asynchronous, multi-modal tools were common.'],
      crit=['Empirical support for the matching hypothesis is mixed, particularly for experienced users.',
            'It treats richness as a fixed property of a medium rather than something socially constructed.'],
      apps=['Remote Work', 'Hybrid Work', 'Distributed Teams'],
      rel=['adaptive-structuration-theory', 'affordance-theory'],
      works=[W('Daft & Lengel', 1986, 'Organizational information requirements, media richness and structural design', 'Management Science')]),

    T('adaptive-structuration-theory', 'Adaptive Structuration Theory', '适应性结构化理论', 'AST',
      ['Information Systems'], 1994,
      'Technology effects emerge from how groups appropriate a technology’s structural features in practice, not from the technology alone.',
      '技术的影响并非由技术本身决定，而是产生于群体在实践中如何"挪用"技术所提供的结构性特征。',
      tags=['structuration theory', 'adaptive structuration theory'],
      kw=['appropriation', 'structuration', 'spirit', 'structural features'],
      core=['autonomy', 'psychological-safety', 'algorithmic-control'],
      mech=['appropriation', 'faithful and unfaithful use', 'emergent structures'],
      out=['autonomy', 'employee-voice'],
      bc=['Effects are group and history dependent, so results do not generalize across implementation contexts.',
          'It explains process better than it predicts point outcomes.'],
      crit=['The core constructs are hard to operationalize, so quantitative tests are rare.',
            '"Spirit" of a technology is analytically slippery and often inferred after the fact.'],
      apps=['Enterprise Systems', 'Algorithmic Management', 'Collaboration Tools'],
      rel=['affordance-theory', 'media-richness-theory'],
      works=[W('DeSanctis & Poole', 1994, 'Capturing the complexity in advanced technology use: Adaptive structuration theory', 'Organization Science'),
             W('Giddens', 1984, 'The Constitution of Society: Outline of the Theory of Structuration', 'Polity Press', 'origin')]),

    T('affordance-theory', 'Affordance Theory', '可供性理论', None,
      ['Information Systems', 'Computational Social Science'], 2013,
      'A technology offers action possibilities that exist in the relation between the artefact and a goal-directed actor, and are actualized rather than automatic.',
      '技术提供的是"行动可能性"，它存在于人工物与有目标的行动者之间的关系中，需要被实现而非自动发生。',
      tags=['affordance theory', 'affordance', 'affordances'],
      kw=['affordance', 'actualization', 'action possibility', 'materiality'],
      core=['autonomy', 'algorithmic-transparency', 'algorithmic-control'],
      mech=['perception of affordance', 'actualization', 'constraint'],
      out=['autonomy', 'employee-voice', 'algorithmic-transparency'],
      bc=['An affordance is relational: it exists only for an actor with a given goal and capability.',
          'Actualization depends on organizational conditions, not only on perception.'],
      crit=['The term is applied so broadly that it sometimes relabels rather than explains.',
            'Affordances are usually identified retrospectively from observed use, risking circularity.'],
      apps=['Algorithmic Management', 'Social Media', 'Platform Work'],
      rel=['adaptive-structuration-theory', 'media-richness-theory'],
      works=[W('Markus & Silver', 2008, 'A foundation for the study of IT effects: A new look at DeSanctis and Poole’s concepts of structural features and spirit', 'Journal of the Association for Information Systems'),
             W('Volkoff & Strong', 2013, 'Critical realism and affordances: Theorizing IT-associated organizational change processes', 'MIS Quarterly')]),

    T('privacy-calculus-theory', 'Privacy Calculus Theory', '隐私计算理论', None,
      ['Information Systems', 'Marketing'], 2006,
      'Disclosure decisions reflect a trade-off in which anticipated benefits are weighed against perceived privacy risk.',
      '个体的信息披露决策是一种权衡：将预期收益与感知到的隐私风险相互比较后作出。',
      tags=['privacy calculus'],
      kw=['privacy', 'disclosure', 'perceived risk', 'trade-off', 'trust'],
      core=['trust', 'algorithmic-transparency', 'algorithmic-monitoring'],
      ante=['algorithmic-transparency', 'algorithmic-monitoring'],
      mech=['risk-benefit trade-off', 'trust', 'perceived control'],
      out=['trust', 'technology-adoption-intention'],
      bc=['Stated privacy concern and actual disclosure diverge systematically (the privacy paradox).',
          'The calculus assumes deliberation, which fits consequential disclosures better than routine ones.'],
      crit=['Most tests use hypothetical scenarios and stated intention rather than observed disclosure.',
            'It underplays the structural asymmetry between individuals and platforms.'],
      apps=['Employee Monitoring', 'Personalization', 'Health Data'],
      rel=['technology-acceptance-model', 'social-exchange-theory'],
      works=[W('Dinev & Hart', 2006, 'An extended privacy calculus model for e-commerce transactions', 'Information Systems Research'),
             W('Culnan & Armstrong', 1999, 'Information privacy concerns, procedural fairness, and impersonal trust: An empirical investigation', 'Organization Science', 'origin')]),

    T('diffusion-of-innovations', 'Diffusion of Innovations', '创新扩散理论', 'DOI',
      ['Information Systems', 'Marketing', 'Management / Strategy'], 1962,
      'Innovations spread through a social system over time via communication channels, with adoption shaped by perceived attributes of the innovation and adopter categories.',
      '创新经由沟通渠道在社会系统中随时间扩散；采纳速度取决于创新被感知的属性以及采纳者所属的类别。',
      tags=['diffusion of innovations', 'diffusion of innovation', 'innovation diffusion'],
      kw=['diffusion', 'adoption', 'relative advantage', 'compatibility', 'trialability'],
      core=['technology-adoption-intention', 'trust'],
      mech=['communication channels', 'social contagion', 'perceived attributes'],
      out=['technology-adoption-intention'],
      bc=['The S-curve describes aggregate diffusion and says little about any individual decision.',
          'Pro-innovation bias: the framework assumes adoption is desirable and under-theorizes rejection.'],
      crit=['Adopter categories are descriptive labels derived from the curve rather than independent predictors.',
            'It underweights supply-side push, pricing, and institutional mandates.'],
      apps=['Technology Adoption', 'Platform Growth', 'AI Adoption'],
      rel=['utaut', 'social-network-theory', 'institutional-theory'],
      works=[W('Rogers', 1962, 'Diffusion of Innovations', 'Free Press')]),
]


# ─────────────────────────────────────────────────────────────────────────────
# Theories — Management / Strategy
# ─────────────────────────────────────────────────────────────────────────────

THEORIES += [
    T('resource-based-view', 'Resource-Based View', '资源基础观', 'RBV',
      ['Management / Strategy'], 1991,
      'Sustained competitive advantage stems from resources that are valuable, rare, imperfectly imitable, and non-substitutable.',
      '持续竞争优势来源于同时具备价值性、稀缺性、难以模仿性与不可替代性的资源。',
      tags=['resource_based_view', 'resource-based view'],
      kw=['resources', 'capabilities', 'competitive advantage', 'imitability', 'VRIN'],
      mech=['resource heterogeneity', 'isolating mechanisms'],
      ante=['resource endowment', 'capability development'],
      out=['competitive advantage', 'firm performance'],
      bc=['The framework explains persistence of advantage better than its original creation.',
          'Resource value is defined relative to a product market, so it is not an intrinsic property.'],
      crit=['Definitions of resources and capabilities are contested, and some formulations risk tautology.',
            'Empirical tests often proxy resources with outcomes, which cannot separate cause from consequence.'],
      apps=['Digital Capabilities', 'Human Capital', 'Platform Strategy'],
      rel=['dynamic-capabilities', 'knowledge-based-view', 'institutional-theory'],
      works=[W('Barney', 1991, 'Firm resources and sustained competitive advantage', 'Journal of Management'),
             W('Wernerfelt', 1984, 'A resource-based view of the firm', 'Strategic Management Journal', 'origin')]),

    T('dynamic-capabilities', 'Dynamic Capabilities', '动态能力理论', 'DC',
      ['Management / Strategy'], 1997,
      'Firms sustain advantage in changing environments by sensing opportunities, seizing them, and reconfiguring their resource base.',
      '在快速变化的环境中，企业通过感知机会、把握机会并重构资源基础来维持竞争优势。',
      tags=['dynamic capabilities', 'dynamic capability'],
      kw=['sensing', 'seizing', 'reconfiguring', 'capabilities', 'change'],
      mech=['sensing', 'seizing', 'reconfiguration'],
      ante=['resource endowment', 'managerial cognition'],
      out=['competitive advantage', 'firm performance'],
      bc=['The value of dynamic capabilities depends on environmental dynamism; in stable settings they may be costly overhead.',
          'They are organizational routines, not individual managerial acts.'],
      crit=['The construct has been criticized as difficult to falsify and prone to tautology.',
            'Measurement varies so widely across studies that cumulative evidence is hard to build.'],
      apps=['Digital Transformation', 'AI Adoption', 'Platform Strategy'],
      rel=['resource-based-view', 'absorptive-capacity', 'organizational-ambidexterity'],
      works=[W('Teece, Pisano & Shuen', 1997, 'Dynamic capabilities and strategic management', 'Strategic Management Journal'),
             W('Eisenhardt & Martin', 2000, 'Dynamic capabilities: What are they?', 'Strategic Management Journal', 'major_extension')]),

    T('knowledge-based-view', 'Knowledge-Based View', '知识基础观', 'KBV',
      ['Management / Strategy'], 1996,
      'Knowledge is the strategically most significant resource, and the firm exists because it integrates specialized knowledge better than markets can.',
      '知识是最具战略意义的资源；企业之所以存在，是因为它比市场更有效地整合分散的专业化知识。',
      tags=['knowledge-based view', 'knowledge based view'],
      kw=['knowledge integration', 'tacit knowledge', 'knowledge transfer', 'coordination'],
      mech=['knowledge integration', 'tacitness', 'coordination mechanisms'],
      out=['competitive advantage', 'innovation'],
      bc=['Tacit knowledge is hard to transfer, which is both the source of advantage and the limit on scaling it.',
          'The argument concerns knowledge integration, not knowledge volume.'],
      crit=['Separating the knowledge-based view from the broader resource-based view is contested.',
            'Knowledge is typically proxied by patents or R&D spend, which capture only codified components.'],
      apps=['Innovation', 'Alliances', 'AI and Knowledge Work'],
      rel=['resource-based-view', 'absorptive-capacity', 'organizational-learning-theory'],
      works=[W('Grant', 1996, 'Toward a knowledge-based theory of the firm', 'Strategic Management Journal'),
             W('Kogut & Zander', 1992, 'Knowledge of the firm, combinative capabilities, and the replication of technology', 'Organization Science', 'origin')]),

    T('absorptive-capacity', 'Absorptive Capacity', '吸收能力理论', 'ACAP',
      ['Management / Strategy', 'Information Systems'], 1990,
      'A firm’s ability to recognize, assimilate, and apply new external knowledge depends on its related prior knowledge.',
      '企业识别、消化并应用外部新知识的能力，取决于它此前已积累的相关知识存量。',
      tags=['absorptive capacity'],
      kw=['absorptive capacity', 'prior knowledge', 'assimilation', 'exploitation'],
      mech=['recognition', 'assimilation', 'transformation', 'exploitation'],
      out=['innovation', 'firm performance'],
      bc=['It is path dependent: firms cannot absorb knowledge far from their existing base.',
          'Potential and realized absorptive capacity have different antecedents and consequences.'],
      crit=['R&D intensity is a weak proxy that conflates investment with capability.',
            'The construct is frequently invoked without measuring its dimensions separately.'],
      apps=['Open Innovation', 'Alliances', 'AI Adoption'],
      rel=['knowledge-based-view', 'dynamic-capabilities', 'organizational-learning-theory'],
      works=[W('Cohen & Levinthal', 1990, 'Absorptive capacity: A new perspective on learning and innovation', 'Administrative Science Quarterly'),
             W('Zahra & George', 2002, 'Absorptive capacity: A review, reconceptualization, and extension', 'Academy of Management Review', 'major_extension')]),

    T('institutional-theory', 'Institutional Theory', '制度理论', None,
      ['Management / Strategy', 'Information Systems'], 1977,
      'Organizational structures and practices are shaped by rules, norms, and cultural-cognitive expectations that confer legitimacy, not only by efficiency.',
      '组织的结构与实践不只由效率决定，也由赋予其合法性的规制性、规范性与文化—认知性制度期待所塑造。',
      tags=['institutional_theory', 'institutional theory', 'neo-institutional theory'],
      kw=['legitimacy', 'isomorphism', 'institutional logics', 'decoupling', 'norms'],
      ante=['regulatory pressure', 'normative pressure', 'mimetic pressure'],
      mech=['legitimacy seeking', 'isomorphism', 'decoupling'],
      out=['practice adoption', 'organizational conformity'],
      bc=['Institutional pressures vary by field maturity; explanations from mature fields transfer poorly to emerging ones.',
          'Conformity and differentiation pressures can operate at the same time.'],
      crit=['Early formulations were criticized for underplaying agency, which later institutional-work research addressed.',
            'Legitimacy is often inferred from adoption rather than measured independently, risking circularity.'],
      apps=['Sustainability Reporting', 'Governance', 'Digital Transformation', 'Platform Regulation'],
      rel=['institutional-logics', 'resource-dependence-theory', 'upper-echelons-theory'],
      works=[W('Meyer & Rowan', 1977, 'Institutionalized organizations: Formal structure as myth and ceremony', 'American Journal of Sociology'),
             W('DiMaggio & Powell', 1983, 'The iron cage revisited: Institutional isomorphism and collective rationality in organizational fields', 'American Sociological Review', 'major_extension')]),

    T('institutional-logics', 'Institutional Logics Perspective', '制度逻辑视角', None,
      ['Management / Strategy'], 1999,
      'Fields are governed by multiple, sometimes competing, socially constructed logics that supply actors with organizing principles and identities.',
      '组织场域受多种社会建构的制度逻辑支配，这些逻辑有时相互竞争，为行动者提供组织原则与身份认同。',
      tags=['institutional logic', 'institutional logics'],
      kw=['logics', 'hybridity', 'competing logics', 'field', 'identity'],
      mech=['logic salience', 'hybridization', 'logic conflict'],
      out=['practice adoption', 'organizational conformity'],
      bc=['Logic conflict is most visible in hybrid organizations spanning fields.',
          'Logics are analytical ideal types, not directly observable entities.'],
      crit=['Identifying which logic is operating often relies on the researcher’s interpretation.',
            'The number and boundaries of logics vary across studies without a shared standard.'],
      apps=['Social Enterprise', 'Healthcare', 'Platform Governance', 'Sustainability'],
      rel=['institutional-theory', 'paradox-theory', 'sensemaking-theory'],
      works=[W('Thornton & Ocasio', 1999, 'Institutional logics and the historical contingency of power in organizations', 'American Journal of Sociology'),
             W('Friedland & Alford', 1991, 'Bringing society back in: Symbols, practices, and institutional contradictions', 'The New Institutionalism in Organizational Analysis', 'origin')]),

    T('transaction-cost-economics', 'Transaction Cost Economics', '交易成本经济学', 'TCE',
      ['Management / Strategy', 'Information Systems'], 1975,
      'Governance choices between market, hybrid, and hierarchy are driven by the costs of transacting under asset specificity, uncertainty, and frequency.',
      '在资产专用性、不确定性与交易频率的条件下，交易成本决定了企业在市场、混合与科层三种治理结构之间的选择。',
      tags=['transaction_cost', 'transaction cost economics', 'transaction cost theory'],
      kw=['asset specificity', 'opportunism', 'bounded rationality', 'governance', 'make-or-buy'],
      mech=['asset specificity', 'safeguarding', 'adaptation'],
      out=['governance choice', 'firm boundaries'],
      bc=['Predictions are sharpest where asset specificity is high and measurable.',
          'It assumes opportunism is a live risk; trust-rich settings may not fit.'],
      crit=['The behavioural assumption of opportunism has been criticized as both unrealistic and self-fulfilling.',
            'Asset specificity is difficult to measure and is frequently proxied crudely.'],
      apps=['Outsourcing', 'Platform Governance', 'Supply Chains', 'Cloud Sourcing'],
      rel=['agency-theory', 'contract-theory', 'resource-dependence-theory'],
      works=[W('Williamson', 1975, 'Markets and Hierarchies: Analysis and Antitrust Implications', 'Free Press'),
             W('Coase', 1937, 'The nature of the firm', 'Economica', 'origin')]),

    T('agency-theory', 'Agency Theory', '委托代理理论', None,
      ['Management / Strategy'], 1976,
      'When a principal delegates to an agent with divergent interests and asymmetric information, contracts and monitoring are used to align behaviour.',
      '当委托人将决策权授予利益不一致且信息不对称的代理人时，需要通过契约设计与监督来对齐双方行为。',
      tags=['agency_theory', 'agency theory', 'principal-agent theory'],
      kw=['agency cost', 'moral hazard', 'incentive alignment', 'monitoring', 'information asymmetry'],
      core=['algorithmic-monitoring', 'trust'],
      mech=['incentive alignment', 'monitoring', 'risk sharing'],
      out=['governance choice', 'firm performance'],
      bc=['It assumes measurable outcomes; where output is unobservable, behaviour-based contracts dominate.',
          'It models a dyad and extends awkwardly to multiple principals with conflicting goals.'],
      crit=['The narrow self-interest assumption ignores intrinsic motivation and can crowd it out in practice.',
            'Its normative use in governance has been criticized for legitimizing incentive structures with harmful side effects.'],
      apps=['Executive Compensation', 'Corporate Governance', 'Platform Work', 'Algorithmic Management'],
      rel=['transaction-cost-economics', 'contract-theory', 'signaling-theory', 'stakeholder-theory'],
      works=[W('Jensen & Meckling', 1976, 'Theory of the firm: Managerial behavior, agency costs and ownership structure', 'Journal of Financial Economics'),
             W('Eisenhardt', 1989, 'Agency theory: An assessment and review', 'Academy of Management Review', 'major_review')]),

    T('signaling-theory', 'Signaling Theory', '信号理论', None,
      ['Management / Strategy', 'Marketing'], 1973,
      'Under information asymmetry, informed parties send costly, hard-to-imitate signals that observers use to infer unobservable quality.',
      '在信息不对称条件下，掌握信息的一方发出代价高昂、难以模仿的信号，观察方据此推断其不可直接观察的质量。',
      tags=['signaling', 'signaling theory', 'signalling theory'],
      kw=['signal', 'information asymmetry', 'credibility', 'screening', 'signal cost'],
      core=['trust', 'algorithmic-transparency'],
      ante=['information-asymmetry'],
      mech=['signal cost', 'signal observability', 'receiver interpretation'],
      out=['trust', 'firm performance'],
      bc=['A signal only separates types if it is genuinely costlier for low-quality senders.',
          'It requires an observable signal and an attentive receiver; both are often assumed rather than shown.'],
      crit=['Many empirical applications label any observable attribute a "signal" without establishing differential cost.',
            'Receiver-side interpretation is theorized far less than sender-side transmission.'],
      apps=['IPOs', 'Entrepreneurial Finance', 'Certification', 'Online Marketplaces'],
      rel=['agency-theory', 'transaction-cost-economics'],
      works=[W('Spence', 1973, 'Job market signaling', 'The Quarterly Journal of Economics'),
             W('Connelly, Certo, Ireland & Reutzel', 2011, 'Signaling theory: A review and assessment', 'Journal of Management', 'major_review')]),

    T('upper-echelons-theory', 'Upper Echelons Theory', '高阶梯队理论', 'UET',
      ['Management / Strategy'], 1984,
      'Organizational outcomes partly reflect the values, experiences, and cognitive frames of senior executives, observable in part through their background characteristics.',
      '组织的战略选择与绩效部分反映高层管理者的价值观、经历与认知框架，这些可通过其背景特征部分观察到。',
      tags=['upper_echelons', 'upper echelons theory', 'upper echelons'],
      kw=['TMT', 'executive characteristics', 'managerial discretion', 'strategic choice'],
      ante=['executive experience', 'executive values', 'TMT composition'],
      mech=['managerial cognition', 'strategic choice', 'managerial discretion'],
      out=['strategic change', 'firm performance'],
      mod=['managerial discretion'],
      bc=['Predictive strength depends on managerial discretion; in low-discretion settings executive characteristics matter less.',
          'Demographic proxies stand in for cognition and are imperfect substitutes for it.'],
      crit=['Using observable demographics as proxies for unobserved cognition is the theory’s most persistent criticism.',
            'Endogenous executive selection makes causal interpretation of executive effects difficult.'],
      apps=['CEO Succession', 'Strategic Change', 'ESG Decisions', 'Digital Strategy'],
      rel=['behavioral-theory-of-the-firm', 'attention-based-view', 'institutional-theory'],
      works=[W('Hambrick & Mason', 1984, 'Upper echelons: The organization as a reflection of its top managers', 'Academy of Management Review'),
             W('Hambrick', 2007, 'Upper echelons theory: An update', 'Academy of Management Review', 'major_review')]),

    T('behavioral-theory-of-the-firm', 'Behavioral Theory of the Firm', '企业行为理论', 'BTOF',
      ['Management / Strategy'], 1963,
      'Firms are coalitions with conflicting goals that satisfice against aspiration levels, searching in response to performance feedback.',
      '企业是目标冲突的联盟，以满意化而非最优化方式对照抱负水平决策，并根据绩效反馈启动问题式搜索。',
      tags=['behavioral_theory_of_firm', 'behavioral theory of the firm'],
      kw=['aspiration level', 'performance feedback', 'problemistic search', 'satisficing', 'slack'],
      mech=['aspiration comparison', 'problemistic search', 'organizational slack'],
      out=['strategic change', 'risk taking'],
      bc=['Predictions hinge on the chosen aspiration reference (historical vs social), which studies operationalize differently.',
          'Responses to performance below aspiration are not symmetric with responses above it.'],
      crit=['Aspiration levels are inferred from models rather than observed, allowing flexible fitting.',
            'The theory predicts direction of search better than the content of what firms find.'],
      apps=['R&D Investment', 'Risk Taking', 'Strategic Change'],
      rel=['upper-echelons-theory', 'organizational-learning-theory', 'attention-based-view'],
      works=[W('Cyert & March', 1963, 'A Behavioral Theory of the Firm', 'Prentice-Hall'),
             W('Greve', 2003, 'Organizational Learning from Performance Feedback', 'Cambridge University Press', 'major_extension')]),

    T('resource-dependence-theory', 'Resource Dependence Theory', '资源依赖理论', 'RDT',
      ['Management / Strategy'], 1978,
      'Organizations depend on external parties for critical resources and act to reduce the uncertainty and power imbalance that dependence creates.',
      '组织在关键资源上依赖外部主体，并会采取行动以降低这种依赖带来的不确定性与权力失衡。',
      tags=['resource dependence', 'resource dependence theory'],
      kw=['dependence', 'power', 'uncertainty', 'interlocks', 'buffering'],
      mech=['dependence reduction', 'co-optation', 'buffering and bridging'],
      out=['governance choice', 'organizational conformity'],
      bc=['Dependence matters most where the resource is critical and concentrated among few suppliers.',
          'It explains structural responses better than the timing of those responses.'],
      crit=['Dependence is often proxied by concentration measures that omit substitutability.',
            'It is difficult to separate empirically from transaction cost predictions.'],
      apps=['Board Interlocks', 'Supply Chains', 'Platform Dependence', 'Alliances'],
      rel=['institutional-theory', 'transaction-cost-economics', 'stakeholder-theory'],
      works=[W('Pfeffer & Salancik', 1978, 'The External Control of Organizations: A Resource Dependence Perspective', 'Harper & Row')]),

    T('stakeholder-theory', 'Stakeholder Theory', '利益相关者理论', None,
      ['Management / Strategy'], 1984,
      'Firms should be managed for the benefit of all parties with a stake in them, and attending to stakeholder relationships is itself a source of value.',
      '企业应为所有利益相关方的利益而管理；妥善经营利益相关者关系本身即是价值创造的来源。',
      tags=['stakeholder theory'],
      kw=['stakeholders', 'legitimacy', 'salience', 'value creation', 'CSR'],
      core=['trust', 'perceived-organizational-support'],
      mech=['stakeholder salience', 'reciprocity', 'legitimacy'],
      out=['firm performance', 'organizational conformity'],
      bc=['Stakeholder salience shifts with power, legitimacy, and urgency rather than being fixed.',
          'Prescriptive and descriptive versions of the theory answer different questions.'],
      crit=['Without a decision rule for trading off stakeholders, it risks being unfalsifiable as a management theory.',
            'Empirical work often reduces it to a CSR score, losing the relational core.'],
      apps=['ESG', 'Corporate Governance', 'Sustainability', 'Platform Regulation'],
      rel=['agency-theory', 'institutional-theory', 'resource-dependence-theory'],
      works=[W('Freeman', 1984, 'Strategic Management: A Stakeholder Approach', 'Pitman'),
             W('Mitchell, Agle & Wood', 1997, 'Toward a theory of stakeholder identification and salience', 'Academy of Management Review', 'major_extension')]),

    T('organizational-ambidexterity', 'Organizational Ambidexterity', '组织双元理论', None,
      ['Management / Strategy'], 1991,
      'Long-run survival requires firms to exploit current capabilities while simultaneously exploring new ones, despite the tension between the two.',
      '企业的长期存续要求在利用现有能力（exploitation）与探索新能力（exploration）之间同时推进，尽管二者存在内在张力。',
      tags=['ambidexterity', 'ambidexterity theory', 'exploration exploitation'],
      kw=['exploration', 'exploitation', 'ambidexterity', 'tension', 'balance'],
      mech=['structural separation', 'contextual ambidexterity', 'temporal cycling'],
      out=['innovation', 'firm performance'],
      bc=['The benefit of ambidexterity depends on environmental dynamism and resource slack.',
          'Structural, contextual, and sequential forms have different requirements and are not interchangeable.'],
      crit=['Exploration and exploitation are measured as a continuum in some studies and as orthogonal in others.',
            'The performance benefit is contingent enough that pooled estimates are hard to interpret.'],
      apps=['Innovation', 'Digital Transformation', 'AI Adoption'],
      rel=['dynamic-capabilities', 'organizational-learning-theory', 'paradox-theory'],
      works=[W('March', 1991, 'Exploration and exploitation in organizational learning', 'Organization Science'),
             W('Tushman & O’Reilly', 1996, 'Ambidextrous organizations: Managing evolutionary and revolutionary change', 'California Management Review', 'major_extension')]),

    T('attention-based-view', 'Attention-Based View', '注意力基础观', 'ABV',
      ['Management / Strategy'], 1997,
      'What a firm does depends on how it channels and distributes the limited attention of its decision makers across issues and answers.',
      '企业的行为取决于它如何在各类议题与方案之间引导和分配决策者有限的注意力。',
      tags=['attention-based view', 'attention based view'],
      kw=['attention', 'issues', 'channels', 'structural distribution', 'focus'],
      mech=['focus of attention', 'situated attention', 'structural distribution of attention'],
      out=['strategic change', 'firm performance'],
      bc=['It applies where attention is genuinely scarce relative to the issue load.',
          'Attention is inferred from communication artefacts rather than observed directly.'],
      crit=['Operationalization usually relies on text counts, which conflate attention with disclosure.',
            'The link from attention to action is assumed more often than tested.'],
      apps=['Strategic Change', 'ESG Disclosure', 'Crisis Response'],
      rel=['behavioral-theory-of-the-firm', 'upper-echelons-theory', 'sensemaking-theory'],
      works=[W('Ocasio', 1997, 'Towards an attention-based view of the firm', 'Strategic Management Journal')]),

    T('sensemaking-theory', 'Sensemaking Theory', '意义建构理论', None,
      ['Management / Strategy', 'OB / HR'], 1995,
      'People construct plausible accounts of ambiguous situations retrospectively, and those accounts shape subsequent action.',
      '人们在事后为模糊情境建构出"说得通"的解释，这些解释反过来塑造其后续行动。',
      tags=['sensemaking'],
      kw=['sensemaking', 'plausibility', 'enactment', 'retrospection', 'ambiguity'],
      core=['psychological-safety', 'trust'],
      mech=['enactment', 'selection', 'retention', 'plausibility over accuracy'],
      out=['strategic change', 'employee-voice'],
      bc=['It concerns ambiguous, unfolding situations rather than routine decisions.',
          'It is a process theory; it does not predict which account will prevail.'],
      crit=['Its core concepts resist quantitative operationalization, limiting cumulative testing.',
            'Retrospective accounts collected by researchers are themselves sensemaking, which complicates inference.'],
      apps=['Crisis Response', 'Digital Transformation', 'Algorithmic Management', 'Change'],
      rel=['attention-based-view', 'institutional-logics', 'paradox-theory'],
      works=[W('Weick', 1995, 'Sensemaking in Organizations', 'Sage'),
             W('Maitlis & Christianson', 2014, 'Sensemaking in organizations: Taking stock and moving forward', 'Academy of Management Annals', 'major_review')]),

    T('paradox-theory', 'Paradox Theory', '悖论理论', None,
      ['Management / Strategy', 'OB / HR'], 2011,
      'Organizations face persistent contradictory yet interdependent demands that cannot be resolved, only navigated through both/and responses.',
      '组织长期面临相互矛盾却又彼此依存的要求，这些张力无法被消解，只能通过"兼顾"而非"取舍"的方式加以驾驭。',
      tags=['paradox theory', 'paradox'],
      kw=['paradox', 'tension', 'both/and', 'contradiction', 'dynamic equilibrium'],
      mech=['acceptance', 'differentiation and integration', 'dynamic equilibrium'],
      out=['organizational conformity', 'innovation'],
      bc=['It applies to persistent tensions, not to dilemmas that a one-time choice resolves.',
          'Latent tensions become salient only under particular conditions such as scarcity or plurality.'],
      crit=['Distinguishing a genuine paradox from a trade-off is often done by assertion.',
            'Quantitative measurement of paradoxical tensions is still underdeveloped.'],
      apps=['Sustainability', 'Social Enterprise', 'Ambidexterity', 'Hybrid Work'],
      rel=['organizational-ambidexterity', 'institutional-logics', 'sensemaking-theory'],
      works=[W('Smith & Lewis', 2011, 'Toward a theory of paradox: A dynamic equilibrium model of organizing', 'Academy of Management Review')]),

    T('organizational-learning-theory', 'Organizational Learning Theory', '组织学习理论', None,
      ['Management / Strategy'], 1978,
      'Organizations encode inferences from experience into routines that guide behaviour, learning at rates shaped by feedback and memory.',
      '组织将从经验中得到的推论编码进例行程序以指导行为；学习速度受反馈质量与组织记忆的影响。',
      tags=['organizational learning theory', 'organizational learning'],
      kw=['routines', 'experience', 'single-loop', 'double-loop', 'learning curve'],
      mech=['experience accumulation', 'routine encoding', 'knowledge transfer'],
      out=['innovation', 'firm performance'],
      bc=['Learning from rare events is unreliable because the sample is small and outcomes are ambiguous.',
          'Success can entrench routines, producing competency traps.'],
      crit=['Learning is usually inferred from performance improvement, which has many other causes.',
            'The organizational level of learning is hard to separate from individual learning and turnover.'],
      apps=['Operations', 'Innovation', 'Safety', 'AI Deployment'],
      rel=['absorptive-capacity', 'behavioral-theory-of-the-firm', 'knowledge-based-view'],
      works=[W('Argyris & Schön', 1978, 'Organizational Learning: A Theory of Action Perspective', 'Addison-Wesley'),
             W('Levitt & March', 1988, 'Organizational learning', 'Annual Review of Sociology', 'major_review')]),

    T('contract-theory', 'Contract Theory', '契约理论', None,
      ['Management / Strategy'], 1986,
      'Because contracts cannot specify every contingency, the allocation of residual control rights determines investment incentives and outcomes.',
      '由于契约无法穷尽所有未来状态，剩余控制权的配置决定了各方的投资激励与最终结果。',
      tags=['contract theory', 'incomplete contracts'],
      kw=['incomplete contracts', 'residual rights', 'hold-up', 'ownership', 'renegotiation'],
      mech=['residual control rights', 'hold-up problem', 'ex ante investment'],
      out=['governance choice', 'firm boundaries'],
      bc=['The framework assumes renegotiation is possible but costly; frictionless renegotiation removes the result.',
          'It is most informative where relationship-specific investment is large.'],
      crit=['Key variables such as contract incompleteness are rarely observable in field data.',
            'Empirical tests are scarce relative to the volume of theoretical development.'],
      apps=['Outsourcing', 'Alliances', 'Platform Contracts', 'Franchising'],
      rel=['transaction-cost-economics', 'agency-theory'],
      works=[W('Grossman & Hart', 1986, 'The costs and benefits of ownership: A theory of vertical and lateral integration', 'Journal of Political Economy'),
             W('Hart & Moore', 1990, 'Property rights and the nature of the firm', 'Journal of Political Economy', 'major_extension')]),

    T('real-options-theory', 'Real Options Theory', '实物期权理论', None,
      ['Management / Strategy'], 1994,
      'Investments under uncertainty carry option value: staging commitment preserves the right, without the obligation, to expand or abandon later.',
      '不确定条件下的投资具有期权价值：分阶段投入保留了未来扩张或放弃的权利而非义务。',
      tags=['real options', 'real options theory'],
      kw=['option value', 'uncertainty', 'staged investment', 'flexibility', 'irreversibility'],
      mech=['deferral option', 'growth option', 'abandonment option'],
      out=['firm performance', 'risk taking'],
      bc=['Option logic requires genuine irreversibility and resolvable uncertainty; without both, standard NPV suffices.',
          'Organizational commitment often prevents the abandonment the model assumes.'],
      crit=['Firms frequently fail to exercise abandonment options, undermining the behavioural realism of the model.',
            'Option value is difficult to measure in field settings, so tests rely on indirect proxies.'],
      apps=['R&D Investment', 'Market Entry', 'AI Infrastructure', 'Platform Investment'],
      rel=['dynamic-capabilities', 'behavioral-theory-of-the-firm'],
      works=[W('Dixit & Pindyck', 1994, 'Investment under Uncertainty', 'Princeton University Press'),
             W('McGrath', 1997, 'A real options logic for initiating technology positioning investments', 'Academy of Management Review', 'major_extension')]),

    T('contingency-theory', 'Contingency Theory', '权变理论', None,
      ['Management / Strategy', 'OB / HR'], 1967,
      'There is no single best way to organize; effective structure depends on fit with the environment, technology, and strategy.',
      '不存在普遍最优的组织方式；有效的结构取决于它与环境、技术与战略之间的匹配。',
      tags=['contingency theory'],
      kw=['fit', 'contingency', 'structure', 'environment', 'differentiation'],
      mech=['structural fit', 'differentiation and integration'],
      out=['firm performance', 'organizational conformity'],
      bc=['Fit can be conceptualized as matching, moderation, or gestalt, and these are not equivalent.',
          'It says less about how organizations move from misfit to fit.'],
      crit=['Fit is often tested with interaction terms that do not match the theoretical form of fit claimed.',
            'It has been criticized for functionalism and for underplaying managerial agency.'],
      apps=['Organizational Design', 'Digital Transformation', 'Governance'],
      rel=['institutional-theory', 'resource-dependence-theory'],
      works=[W('Lawrence & Lorsch', 1967, 'Differentiation and integration in complex organizations', 'Administrative Science Quarterly'),
             W('Burns & Stalker', 1961, 'The Management of Innovation', 'Tavistock', 'origin')]),
]


# ─────────────────────────────────────────────────────────────────────────────
# Theories — Marketing and Computational Social Science
# ─────────────────────────────────────────────────────────────────────────────

THEORIES += [
    T('theory-of-planned-behavior', 'Theory of Planned Behavior', '计划行为理论', 'TPB',
      ['Marketing', 'Information Systems', 'OB / HR'], 1991,
      'Attitude, subjective norm, and perceived behavioural control shape intention, which together with control predicts behaviour.',
      '态度、主观规范与感知行为控制共同形成行为意向；意向与实际控制感一起预测行为。',
      tags=['theory of planned behavior', 'theory of planned behaviour', 'tpb'],
      kw=['attitude', 'subjective norm', 'perceived behavioural control', 'intention'],
      core=['technology-adoption-intention', 'trust'],
      mech=['attitude', 'subjective norm', 'perceived control'],
      out=['technology-adoption-intention'],
      bc=['The intention–behaviour gap is largest for behaviours requiring sustained effort or resources.',
          'It assumes deliberative processing and fits habitual behaviour poorly.'],
      crit=['Intention explains far less behavioural variance than the model implies in field settings.',
            'It omits affect, habit, and situational constraint, which later models add.'],
      apps=['Sustainable Consumption', 'Health Behaviour', 'Technology Adoption'],
      rel=['technology-acceptance-model', 'social-cognitive-theory'],
      works=[W('Ajzen', 1991, 'The theory of planned behavior', 'Organizational Behavior and Human Decision Processes'),
             W('Fishbein & Ajzen', 1975, 'Belief, Attitude, Intention, and Behavior: An Introduction to Theory and Research', 'Addison-Wesley', 'origin')]),

    T('prospect-theory', 'Prospect Theory', '前景理论', None,
      ['Marketing', 'Management / Strategy'], 1979,
      'People evaluate outcomes as gains and losses relative to a reference point, are loss averse, and distort probabilities.',
      '人们相对于某个参照点将结果编码为收益或损失，表现出损失厌恶，并对概率进行非线性加权。',
      tags=['prospect theory'],
      kw=['loss aversion', 'reference point', 'framing', 'probability weighting', 'risk'],
      mech=['reference dependence', 'loss aversion', 'probability weighting'],
      out=['risk taking'],
      bc=['Predictions depend entirely on the reference point, which is often unobserved and assumed.',
          'Effects attenuate with market experience and repeated play in some settings.'],
      crit=['Reference-point assumptions give the theory considerable post-hoc flexibility.',
            'Loss-aversion magnitude estimates vary widely and some replications are contested.'],
      apps=['Pricing', 'Framing Effects', 'Executive Risk Taking', 'Negotiation'],
      rel=['behavioral-theory-of-the-firm', 'construal-level-theory'],
      works=[W('Kahneman & Tversky', 1979, 'Prospect theory: An analysis of decision under risk', 'Econometrica'),
             W('Tversky & Kahneman', 1992, 'Advances in prospect theory: Cumulative representation of uncertainty', 'Journal of Risk and Uncertainty', 'major_extension')]),

    T('construal-level-theory', 'Construal Level Theory', '解释水平理论', 'CLT',
      ['Marketing', 'OB / HR'], 2010,
      'Psychological distance shifts mental representation between abstract, high-level construals and concrete, low-level ones, changing evaluation and choice.',
      '心理距离会使心理表征在抽象的高解释水平与具体的低解释水平之间切换，从而改变评价与选择。',
      tags=['construal level theory', 'construal level'],
      kw=['psychological distance', 'abstraction', 'temporal distance', 'construal'],
      mech=['distance-construal match', 'abstraction', 'fit effects'],
      out=['technology-adoption-intention', 'risk taking'],
      bc=['Effects rely on manipulating one distance dimension while others stay constant, which is hard in the field.',
          'Construal level is a state, not a trait, so timing of measurement matters.'],
      crit=['Several classic effects have faced replication difficulties.',
            'Distance manipulations often change more than construal level alone.'],
      apps=['Advertising', 'Sustainability Messaging', 'Remote Leadership'],
      rel=['prospect-theory', 'elaboration-likelihood-model'],
      works=[W('Trope & Liberman', 2010, 'Construal-level theory of psychological distance', 'Psychological Review')]),

    T('elaboration-likelihood-model', 'Elaboration Likelihood Model', '精细加工可能性模型', 'ELM',
      ['Marketing', 'Information Systems'], 1986,
      'Persuasion follows a central route when motivation and ability to process are high, and a peripheral route when they are low.',
      '当个体的加工动机与能力较高时，说服沿中心路径发生；当二者较低时，则沿边缘路径依赖简单线索。',
      tags=['elaboration likelihood model', 'elaboration likelihood'],
      kw=['central route', 'peripheral route', 'elaboration', 'persuasion', 'involvement'],
      core=['trust', 'algorithmic-transparency'],
      mech=['elaboration likelihood', 'argument quality', 'peripheral cues'],
      out=['trust', 'technology-adoption-intention'],
      bc=['Route assignment depends on measured motivation and ability, not assumed from context alone.',
          'Attitudes formed centrally are more persistent and resistant than peripherally formed ones.'],
      crit=['Route classification is often inferred from results rather than established independently.',
            'The two routes are difficult to separate cleanly in field data.'],
      apps=['Advertising', 'Online Reviews', 'AI Explanations', 'Recommendation Systems'],
      rel=['theory-of-planned-behavior', 'construal-level-theory'],
      works=[W('Petty & Cacioppo', 1986, 'The elaboration likelihood model of persuasion', 'Advances in Experimental Social Psychology')]),

    T('service-dominant-logic', 'Service-Dominant Logic', '服务主导逻辑', 'S-D Logic',
      ['Marketing'], 2004,
      'Value is co-created with customers through the application of operant resources, rather than embedded in goods and delivered by firms.',
      '价值并非嵌入产品由企业单向交付，而是通过运用操作性资源与顾客共同创造。',
      tags=['service-dominant logic', 'service dominant logic'],
      kw=['co-creation', 'operant resources', 'value-in-use', 'service ecosystem'],
      core=['trust', 'employee-engagement'],
      mech=['resource integration', 'value co-creation', 'service exchange'],
      out=['trust', 'firm performance'],
      bc=['It is a lens rather than a predictive model; testable propositions must be derived first.',
          'Value-in-use is contextual and resists standardized measurement.'],
      crit=['Critics argue its axioms are difficult to falsify as stated.',
            'Empirical work often reduces co-creation to participation, losing the theoretical claim.'],
      apps=['Service Design', 'Platform Ecosystems', 'B2B Marketing'],
      rel=['stakeholder-theory', 'knowledge-based-view'],
      works=[W('Vargo & Lusch', 2004, 'Evolving to a new dominant logic for marketing', 'Journal of Marketing'),
             W('Vargo & Lusch', 2016, 'Institutions and axioms: An extension and update of service-dominant logic', 'Journal of the Academy of Marketing Science', 'major_extension')]),

    T('brand-equity-theory', 'Brand Equity Theory', '品牌资产理论', 'CBBE',
      ['Marketing'], 1993,
      'Brand knowledge held in consumer memory differentially shapes response to marketing, creating value beyond the product itself.',
      '消费者记忆中的品牌知识会差异化地影响其对营销活动的反应，从而创造超出产品本身的价值。',
      tags=['brand equity theory', 'brand equity'],
      kw=['brand awareness', 'brand image', 'brand associations', 'customer-based brand equity'],
      core=['trust'],
      mech=['brand awareness', 'brand associations', 'differential response'],
      out=['firm performance', 'trust'],
      bc=['Customer-based and financial brand equity are related but distinct and should not be substituted.',
          'Associations are category specific and do not transfer automatically.'],
      crit=['Measurement approaches proliferate without convergence, complicating comparison.',
            'Causality between brand equity and performance is difficult to establish.'],
      apps=['Branding', 'Brand Extensions', 'Platform Brands'],
      rel=['signaling-theory', 'service-dominant-logic'],
      works=[W('Keller', 1993, 'Conceptualizing, measuring, and managing customer-based brand equity', 'Journal of Marketing'),
             W('Aaker', 1991, 'Managing Brand Equity', 'Free Press', 'origin')]),

    T('consumer-culture-theory', 'Consumer Culture Theory', '消费者文化理论', 'CCT',
      ['Marketing'], 2005,
      'Consumption is a site of cultural meaning-making through which people construct identity, and marketplace ideologies shape those meanings.',
      '消费是文化意义生成的场域，人们借由消费建构身份认同，而市场意识形态又反过来塑造这些意义。',
      tags=['consumer culture theory'],
      kw=['identity projects', 'marketplace cultures', 'ideology', 'symbolic consumption'],
      mech=['identity construction', 'meaning transfer', 'marketplace ideology'],
      out=['trust'],
      bc=['It is interpretive; findings are context bound by design and not intended to generalize statistically.',
          'It studies meaning rather than predicting purchase.'],
      crit=['Its relationship to managerial relevance is contested within the field.',
            'Findings depend heavily on researcher interpretation and are hard to replicate.'],
      apps=['Brand Communities', 'Sustainable Consumption', 'Platform Consumption'],
      rel=['social-identity-theory', 'institutional-logics'],
      works=[W('Arnould & Thompson', 2005, 'Consumer culture theory (CCT): Twenty years of research', 'Journal of Consumer Research')]),

    T('social-capital-theory', 'Social Capital Theory', '社会资本理论', None,
      ['Computational Social Science', 'Management / Strategy', 'OB / HR'], 1998,
      'Resources embedded in and available through networks of relationships confer advantage on individuals and collectives.',
      '嵌入于关系网络之中、并可通过该网络动员的资源，为个体与集体带来优势。',
      tags=['social capital theory', 'social capital'],
      kw=['social capital', 'structural', 'relational', 'cognitive', 'networks'],
      core=['trust', 'social-support', 'psychological-safety'],
      ante=['social-support', 'trust'],
      mech=['structural dimension', 'relational dimension', 'cognitive dimension'],
      out=['employee-voice', 'trust', 'innovation'],
      bc=['Bonding and bridging capital have different and sometimes opposing consequences.',
          'Social capital can be a liability where closure enforces obsolete norms.'],
      crit=['The term is applied to network structure, trust, and norms interchangeably, blurring what is measured.',
            'Direction of causality between social capital and outcomes is frequently unresolved.'],
      apps=['Innovation', 'Teams', 'Online Communities', 'Knowledge Sharing'],
      rel=['social-network-theory', 'structural-holes-theory', 'social-exchange-theory'],
      works=[W('Nahapiet & Ghoshal', 1998, 'Social capital, intellectual capital, and the organizational advantage', 'Academy of Management Review'),
             W('Coleman', 1988, 'Social capital in the creation of human capital', 'American Journal of Sociology', 'origin')]),

    T('social-network-theory', 'Social Network Theory', '社会网络理论', 'SNA',
      ['Computational Social Science', 'Management / Strategy'], 1973,
      'Outcomes depend on the pattern of ties among actors, so position in a network conveys information, influence, and constraint.',
      '结果取决于行动者之间连带关系的整体格局；网络中的位置本身即带来信息、影响力与约束。',
      tags=['network theory', 'social network theory', 'social network analysis'],
      kw=['ties', 'centrality', 'structure', 'network position', 'contagion'],
      core=['social-support', 'trust'],
      mech=['information flow', 'social influence', 'structural constraint'],
      out=['innovation', 'employee-voice', 'turnover-intention'],
      bc=['Network boundaries must be defined by a stated rule; results are sensitive to that choice.',
          'Ties are usually measured at one moment though networks evolve.'],
      crit=['Homophily and influence are observationally equivalent without a design that separates them.',
            'Missing ties bias every centrality measure, and coverage is rarely reported.'],
      apps=['Knowledge Sharing', 'Diffusion', 'Online Platforms', 'Team Performance'],
      rel=['structural-holes-theory', 'weak-ties-theory', 'social-capital-theory'],
      works=[W('Granovetter', 1973, 'The strength of weak ties', 'American Journal of Sociology'),
             W('Borgatti & Halgin', 2011, 'On network theory', 'Organization Science', 'major_review')]),

    T('structural-holes-theory', 'Structural Holes Theory', '结构洞理论', None,
      ['Computational Social Science', 'Management / Strategy'], 1992,
      'Actors who bridge disconnected groups gain information and control advantages from occupying the gap between them.',
      '连接彼此不相往来群体的行动者，因占据群体之间的"空洞"位置而获得信息优势与控制优势。',
      tags=['structural holes', 'structural hole theory'],
      kw=['brokerage', 'structural holes', 'bridging', 'constraint', 'tertius gaudens'],
      core=['trust', 'social-support'],
      mech=['information brokerage', 'control benefits', 'non-redundant ties'],
      out=['innovation', 'firm performance'],
      bc=['Brokerage benefits depend on the actor being able to act on the position, not merely occupy it.',
          'Brokerage can carry social costs where closure norms are strong.'],
      crit=['Brokerage and closure benefits are context dependent, and the debate between them remains unsettled.',
            'Most evidence is cross-sectional, leaving selection into broker positions unaddressed.'],
      apps=['Innovation', 'Career Mobility', 'Alliance Networks'],
      rel=['social-network-theory', 'weak-ties-theory', 'social-capital-theory'],
      works=[W('Burt', 1992, 'Structural Holes: The Social Structure of Competition', 'Harvard University Press')]),

    T('weak-ties-theory', 'Strength of Weak Ties', '弱连带理论', None,
      ['Computational Social Science', 'OB / HR'], 1973,
      'Weak ties bridge otherwise separate social circles and therefore carry novel information that strong ties do not.',
      '弱连带跨越了原本彼此分离的社交圈，因而能传递强连带无法带来的新信息。',
      tags=['weak ties', 'strength of weak ties'],
      kw=['weak ties', 'strong ties', 'bridges', 'novel information', 'job search'],
      core=['social-support', 'trust'],
      mech=['bridging', 'information novelty', 'reach'],
      out=['turnover-intention', 'innovation'],
      bc=['Weak ties help for information diffusion but not for transferring complex or tacit knowledge.',
          'The advantage depends on the tie actually bridging, not merely being weak.'],
      crit=['Tie strength is measured inconsistently (frequency, closeness, duration) across studies.',
            'Field experiments give more mixed results than the original observational evidence.'],
      apps=['Job Search', 'Information Diffusion', 'Online Networks', 'Remote Work'],
      rel=['social-network-theory', 'structural-holes-theory', 'social-capital-theory'],
      works=[W('Granovetter', 1973, 'The strength of weak ties', 'American Journal of Sociology'),
             W('Granovetter', 1985, 'Economic action and social structure: The problem of embeddedness', 'American Journal of Sociology', 'major_extension')]),

    T('game-theory', 'Game Theory', '博弈论', None,
      ['Management / Strategy', 'Marketing', 'Computational Social Science'], 1944,
      'Strategic outcomes are analysed as equilibria among interdependent decision makers who anticipate each other’s best responses.',
      '将战略结果分析为相互依赖的决策者之间的均衡，每一方都预期并回应对方的最优反应。',
      tags=['game theory'],
      kw=['equilibrium', 'strategic interaction', 'payoffs', 'best response', 'commitment'],
      mech=['best response', 'equilibrium selection', 'commitment'],
      out=['governance choice', 'firm performance'],
      bc=['Predictions depend on the assumed information structure and payoff specification.',
          'Multiple equilibria often exist, and the theory alone does not select among them.'],
      crit=['Behavioural evidence repeatedly departs from equilibrium predictions in laboratory settings.',
            'Model results are sensitive to assumptions that are rarely observable in the field.'],
      apps=['Pricing', 'Platform Competition', 'Auctions', 'Negotiation'],
      rel=['agency-theory', 'signaling-theory', 'contract-theory'],
      works=[W('von Neumann & Morgenstern', 1944, 'Theory of Games and Economic Behavior', 'Princeton University Press'),
             W('Nash', 1950, 'Equilibrium points in n-person games', 'Proceedings of the National Academy of Sciences', 'major_extension')]),
]


# The attached Management and Organization 60 scan contributes the 49 chapters
# that were absent from the first scaffold, while the domain pack adds
# operations, supply chain, decision, finance, accounting, entrepreneurship,
# international business, and analytics / OR coverage.  Existing entries are
# retained and annotated with the verified chapter-start page from the scan.
THEORIES += BOOK_THEORIES + DOMAIN_THEORIES

# Long-form analysis, attached where it has been written.  Coverage is partial by
# design; `deep_dive_status` records which theories carry one so the page can say
# so instead of implying an analysis that does not exist.
def _attach_deep_dives(entities, dives):
    for _entity in entities:
        _dive = dives.get(_entity['id'])
        if _dive:
            _entity['deep_dive'] = _dive
            _entity['deep_dive_status'] = _dive['status']
        else:
            _entity['deep_dive_status'] = 'not_written'


_attach_deep_dives(THEORIES, DEEP_DIVES)
_attach_deep_dives(CONSTRUCTS, CONSTRUCT_DIVES)
_attach_deep_dives(METHODS, METHOD_DIVES)
_BOOK_SOURCE_TEXT = _load_book_source_text_map()
for _theory in THEORIES:
    for _work in _theory.get('seminal_works', []):
        _work.setdefault('source_role', {
            'origin': 'theory_origin',
            'major_review': 'theory_review',
            'major_extension': 'theory_extension',
        }.get(_work.get('kind'), 'theory_source'))
        _work.setdefault('access_status', 'not_checked')
        _work.setdefault('landing_url', None)
        _work.setdefault('full_text_url', None)
        _work.setdefault('full_text_version', None)
        _work.setdefault('license', None)
        _work.setdefault('local_path', None)
        _work.setdefault('retrieved_at', None)
        _work.setdefault('retrieval_note', None)
    if _theory['id'] in BOOK60_SOURCE_PAGES:
        _theory['source_pack'] = 'management-organization-60'
        _theory['source_page'] = BOOK60_SOURCE_PAGES[_theory['id']]
        if _theory['id'] in BOOK60_EXISTING_IDS:
            _theory['source_status'] = 'book_scan_scaffold'
            _theory['source_note'] = (
                'Chapter title and printed starting page checked against the attached scan; '
                'chapter text is not yet OCR-verified.'
            )
        _source_text = _BOOK_SOURCE_TEXT.get(_theory['id'])
        if _source_text:
            _theory['source_text'] = _source_text
            _theory['source_note'] = (
                'Chapter title and printed starting page were checked against the attached '
                'scan. A separate local OCR text layer is available for page search; its '
                'claims, measurements, and citations still require human review against the '
                'original page.'
            )


# Construct and method pages use the same source-record shape as theory pages,
# but their source roles distinguish construct definitions/measurement papers
# and method foundations.  Keeping one list shape makes the evidence layer
# queryable across all three entity types without pretending that the sources
# answer the same scholarly question.
for _kind, _items in (('constructs', CONSTRUCTS), ('methods', METHODS)):
    for _entity in _items:
        _entity['seminal_works'] = source_works_for(_kind, _entity['id'])
        for _work in _entity['seminal_works']:
            _work.setdefault('access_status', 'not_checked')
            _work.setdefault('landing_url', None)
            _work.setdefault('full_text_url', None)
            _work.setdefault('full_text_version', None)
            _work.setdefault('license', None)
            _work.setdefault('local_path', None)
            _work.setdefault('retrieved_at', None)
            _work.setdefault('retrieval_note', None)
        _entity['source_coverage_status'] = (
            'candidate_sources_loaded' if _entity['seminal_works']
            else 'source_search_pending'
        )
        _entity['source_coverage_note'] = (
            'Candidate origin/measurement or method-foundation sources are loaded; '
            'verify the bibliographic match and primary source before manuscript use.'
        )


for _kind, _items in (('theories', THEORIES), ('constructs', CONSTRUCTS), ('methods', METHODS)):
    for _entity in _items:
        for _work in _entity.get('seminal_works', []):
            _override = SOURCE_OVERRIDES.get((_kind, _entity['id'], _work.get('title')))
            if _override:
                _work.update(_override)


# -----------------------------------------------------------------------------
# Build
# -----------------------------------------------------------------------------

PROVENANCE = (
    'This is a curated research scaffold for navigation and method planning. It is not a '
    'publication-ready literature review. "tags" are precise classifier tags that denote the '
    'entity; "broad_tags" are umbrella tags whose counts are reported separately because they '
    'cover more than this entity. "seminal_works" are source candidates shared by Theory, '
    'Construct, and Method records. They start as pending_verification; run '
    'scripts/verify_research_sources.py to resolve them against OpenAlex or Crossref and then '
    'resolve open-access locations through the source-access workflow. Verified source fields '
    'and access fields are preserved when this scaffold is regenerated. '
    'Verify every definition, origin year, measurement record, and citation against '
    'the primary source before using it in a manuscript.'
)


def _check_references():
    """A dangling reference renders as a silently empty section, so fail loudly."""
    tids = {t['id'] for t in THEORIES}
    cids = {c['id'] for c in CONSTRUCTS}
    mids = {m['id'] for m in METHODS}
    problems = []

    for theory in THEORIES:
        for ref in theory['core_constructs']:
            if ref not in cids:
                problems.append(('theory', theory['id'], 'core_constructs', ref))
        for ref in theory['related_theories']:
            if ref not in tids:
                problems.append(('theory', theory['id'], 'related_theories', ref))
        for field in ('antecedents', 'outcomes', 'moderators'):
            for ref in theory[field]:
                # These fields mix construct ids with free-text mechanism labels;
                # only a hyphenated token is meant to be an id.
                if '-' in ref and ' ' not in ref and ref not in cids and ref not in tids:
                    problems.append(('theory', theory['id'], field, ref))
        for pathway in (theory.get('conceptual_model') or {}).get('pathways', []):
            for step in pathway['steps']:
                if step not in cids:
                    problems.append(('theory', theory['id'], 'conceptual_model', step))

    for construct in CONSTRUCTS:
        for ref in construct['related_theories']:
            if ref not in tids:
                problems.append(('construct', construct['id'], 'related_theories', ref))
        for field in ('antecedents', 'outcomes', 'mediators', 'moderators'):
            for ref in construct[field]:
                if ref not in cids:
                    problems.append(('construct', construct['id'], field, ref))

    for method in METHODS:
        for ref in method['related_methods']:
            if ref not in mids:
                problems.append(('method', method['id'], 'related_methods', ref))

    for kind, items in (('theory', THEORIES), ('construct', CONSTRUCTS), ('method', METHODS)):
        seen = set()
        for item in items:
            if item['id'] in seen:
                problems.append((kind, item['id'], 'duplicate_id', item['id']))
            seen.add(item['id'])
        for item in items:
            overlap = set(item.get('tags') or []) & set(item.get('broad_tags') or [])
            if overlap:
                problems.append((kind, item['id'], 'tag_is_both_precise_and_broad', sorted(overlap)))
    return problems


def _preserve_verified_work_fields(catalog):
    """Carry source-verification fields across a scaffold regeneration.

    Theory definitions remain source-controlled in this module, while DOI and
    source matches are derived metadata written to the JSON catalog. A rebuild
    must not silently erase a prior OpenAlex or Crossref match.
    """
    if not OUT.exists():
        return 0
    try:
        previous = json.loads(OUT.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return 0
    verified = {}
    pending_notes = {}
    for kind in ('theories', 'constructs', 'methods'):
        for entity in previous.get(kind, []):
            for work in entity.get('seminal_works', []):
                key = (kind, entity.get('id'), work.get('title'))
                if work.get('verification') in {'verified_openalex', 'verified_crossref', 'verified_pubmed'}:
                    verified[key] = work
                elif work.get('verification') == PENDING and work.get('verification_note'):
                    pending_notes[key] = work['verification_note']
                if work.get('access_status') not in {None, 'not_checked'}:
                    verified.setdefault(key, work)

    preserved = 0
    for kind in ('theories', 'constructs', 'methods'):
        for entity in catalog[kind]:
            for work in entity.get('seminal_works', []):
                old = verified.get((kind, entity.get('id'), work.get('title')))
                if old:
                    for key, value in old.items():
                        if key not in {'authors', 'year', 'title', 'venue', 'kind', 'source_role'}:
                            work[key] = value
                    preserved += 1
                    continue
                note = pending_notes.get((kind, entity.get('id'), work.get('title')))
                if note and work.get('verification') not in {'verified_openalex', 'verified_crossref', 'verified_pubmed'}:
                    work['verification_note'] = note
    return preserved


def main():
    problems = _check_references()
    if problems:
        for problem in problems:
            print('INVALID', problem)
        raise SystemExit('catalog has %d unresolved references' % len(problems))

    catalog = {
        'schema_version': 6,
        'catalog_status': 'demo_catalog',
        'provenance_note': PROVENANCE,
        'bilingual': True,
        'theories': THEORIES,
        'constructs': CONSTRUCTS,
        'methods': METHODS,
    }
    preserved = _preserve_verified_work_fields(catalog)
    # Authoritative primary-index corrections take precedence over a stale
    # pending note carried from an earlier scaffold build.
    for _kind, _items in (('theories', THEORIES), ('constructs', CONSTRUCTS), ('methods', METHODS)):
        for _entity in _items:
            for _work in _entity.get('seminal_works', []):
                _override = SOURCE_OVERRIDES.get((_kind, _entity['id'], _work.get('title')))
                if _override:
                    _work.update(_override)
    # Discipline tags. Methods had none at all, which left the Methods tab's
    # discipline filter returning zero rows for every discipline; theories and
    # constructs were under-tagged where the work spans channels. See
    # scripts/research_catalog_disciplines.py for what is corpus-corroborated and
    # what is editorial judgement.
    _disc_changes = apply_disciplines(
        catalog["theories"], catalog["constructs"], catalog["methods"])

    OUT.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + chr(10), encoding='utf-8')

    from collections import Counter
    disciplines = Counter(d for t in THEORIES for d in t['discipline'])
    categories = Counter(m['category'] for m in METHODS)
    works = sum(len(entity.get('seminal_works', []))
                for kind in ('theories', 'constructs', 'methods')
                for entity in catalog[kind])
    print('theories   %d  (%d total source records; %d verified/access fields preserved)' %
          (len(THEORIES), works, preserved))
    print('constructs %d' % len(CONSTRUCTS))
    print('methods    %d  %s' % (len(METHODS), dict(categories)))
    print('theory disciplines %s' % dict(disciplines))
    print('disciplines: set on %d methods; %d theories/constructs extended by %d tags'
          % (_disc_changes['methods_set'], _disc_changes['entities_extended'],
             _disc_changes['disciplines_added']))
    print('wrote', OUT)


if __name__ == '__main__':
    main()
