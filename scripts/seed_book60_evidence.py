#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Seed the first thirty-five book chapters with auditable, page-located T-C-M notes.

This file is an explicit human-review record, not an OCR importer.  The notes
are short paraphrases made after checking the cited pages in the original scan.
They do not copy chapter prose or scale items, and they do not promote any
chapter coding to verified primary-source evidence.  A later rerun preserves
non-empty user coding and avoids duplicate page notes.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import json

try:
    from scripts.build_research_evidence_queue import DEFAULT_OUTPUT, build_queue
except ModuleNotFoundError:  # direct ``python scripts/...`` invocation
    from build_research_evidence_queue import DEFAULT_OUTPUT, build_queue


CHECKED = 'checked_against_original'
PRIMARY_SOURCE_REVIEW_FLAG = 'primary_source_crosscheck_required'
PARTIAL_REVIEW_FLAG = 'partial_human_coding'
REMOVED_PENDING_FLAG = 'no_tcm_claim_until_human_coding'


def _entry(printed_page, pdf_page, kind, note):
    return {
        'printed_page': printed_page,
        'pdf_page': pdf_page,
        'kind': kind,
        'quote_or_note': note,
        'source_check': CHECKED,
    }


# All text below is a compact paraphrase of the cited page, not a verbatim
# excerpt.  The page numbers were checked against the original scan.
EVIDENCE_UPDATES = {
    'affective-events-theory': {
        'coding': {
            'definition': (
                'A workplace affect theory in which work events generate affective '
                'reactions that shape work attitudes and behavior; work-environment '
                'features and traits condition the process.'
            ),
            'constructs': [
                'work events',
                'work-environment features',
                'affective reactions (mood and emotion)',
                'work attitudes / job satisfaction',
                'affect-driven behavior',
                'judgment-driven behavior',
                'positive and negative affectivity',
            ],
            'mechanisms': [
                'event -> affect -> attitude -> behavior',
                'cognitive appraisal of relevance, severity, and coping resources',
                'a non-affective standards-comparison route alongside an affective route',
                'traits moderate event-to-affect links and can directly relate to attitudes',
            ],
            'boundary_conditions': [
                'Events are more likely to elicit affect when they relate to goals or values.',
                'The chapter emphasizes internal organizational events and individual-level affect.',
                'External events and group-level affect are identified as underdeveloped areas.',
            ],
            'criticisms': [
                'The chapter notes limited coverage of external events and collective affect.',
                'The event/environment distinction changes when events become frequent or predictable.',
            ],
            'methods': [
                'Daily-diary design: a cited study followed 64 full-time workers for three weeks.',
                'Repeated longitudinal observations of emotions, attitudes, and behavior.',
                'A cited study combined qualitative and quantitative evidence for creativity.',
            ],
            'cited_works': [
                'Weiss & Cropanzano (1996)',
                'Judge et al. (2006)',
                'Rodell & Judge (2009)',
                'Amabile et al. (2005)',
                'Lanaj et al. (2016)',
            ],
        },
        'evidence': [
            _entry(1, 18, 'definition',
                   'The chapter introduces the 1996 AET proposal as a link among work events, affect, attitudes, and behavior.'),
            _entry(4, 21, 'construct',
                   'The framework diagram places work-environment features, work events, affective reactions, work attitudes, traits, and two behavior routes in one model.'),
            _entry(5, 22, 'construct',
                   'Affective reaction is distinguished into mood and emotion; appraisal of relevance and severity precedes affect, with a secondary assessment of resources.'),
            _entry(6, 23, 'mechanism',
                   'The chapter contrasts standards-based comparison with an affective route from events to affect and attitudes; hassles and uplifts are examples.'),
            _entry(6, 23, 'boundary_condition',
                   'Positive/negative affectivity is described as a trait-level moderator of event-to-affect links and a direct correlate of appraisal or satisfaction.'),
            _entry(7, 24, 'method',
                   'Cited applications include daily diary, repeated observations, and a mixed qualitative-quantitative study; these are chapter-reported examples, not primary-source verification.'),
            _entry(8, 25, 'criticism',
                   'The evaluation summarizes the event-affect-attitude-behavior chain and notes the emphasis on internal organizational events and individual affect.'),
        ],
    },
    'broaden-and-build-theory': {
        'coding': {
            'definition': (
                'Positive emotions broaden the momentary thought-action repertoire and '
                'thereby build durable intellectual, physical, psychological, and social '
                'resources that support later adaptation.'
            ),
            'constructs': [
                'positive emotions',
                'momentary thought-action repertoire',
                'intellectual resources',
                'physical resources',
                'psychological resources',
                'social resources',
                'positive-emotion upward spiral',
            ],
            'mechanisms': [
                'broadening of attention, cognition, and action options',
                'building durable personal resources through repeated broadened activity',
                'undoing of lingering negative cardiovascular/affective activation',
                'upward spiral from positive emotion to resources and later positive emotion',
            ],
            'boundary_conditions': [
                'The theory distinguishes positive-emotion effects from the narrowing action tendencies of negative emotions.',
                'The chapter notes that different positive emotions may not have identical effects.',
                'The chapter identifies open questions about mechanisms, timing, and when resources are built.',
            ],
            'criticisms': [
                'The evaluation calls for clearer neural mechanisms connecting broadening and building.',
                'The chapter flags theory boundaries and possible links with embodied-cognition accounts.',
            ],
            'measurement_scales': [
                {
                    'name': 'Modified Differential Emotions Scale (mDES)',
                    'source': 'Fredrickson (2013)',
                    'metadata': '20 emotion items: 10 positive and 10 negative; chapter reports 0-4 intensity/frequency response options and aggregation options.',
                    'status': 'chapter-reported metadata; do not copy items; primary-source verification required',
                },
            ],
            'methods': [
                'Laboratory emotion-induction experiment comparing positive, neutral, and sad clips after anxiety induction.',
                'Cardiovascular recovery was used in the cited undoing example.',
                'The chapter also cites experimental work on broadened cognition and resources.',
            ],
            'cited_works': [
                'Fredrickson (1998)',
                'Fredrickson (2001)',
                'Fredrickson (2013)',
                'Fredrickson et al. (2000)',
                'Fredrickson & Joiner (2002)',
            ],
        },
        'evidence': [
            _entry(13, 30, 'definition',
                   'The chapter states that positive emotions broaden the momentary thought-action repertoire and build durable personal resources.'),
            _entry(14, 31, 'mechanism',
                   'The broaden hypothesis concerns more flexible attention, cognition, and action; the build hypothesis concerns resources accumulated over time.'),
            _entry(15, 32, 'construct',
                   'The resource categories are intellectual, physical, psychological, and social; examples are described without reproducing instrument items.'),
            _entry(15, 32, 'mechanism',
                   'The undoing and upward-spiral hypotheses are presented as auxiliary processes linking positive emotion, recovery, resources, and later adaptation.'),
            _entry(16, 33, 'criticism',
                   'The evaluation highlights unresolved neural mechanisms, emotion-specific differences, boundary questions, and embodied-cognition overlap.'),
            _entry(16, 33, 'measurement',
                   'The chapter introduces mDES as a measurement source and gives Fredrickson (2013) as the cited reference.'),
            _entry(17, 34, 'measurement',
                   'mDES metadata in the chapter describes positive/negative emotion coverage and a 0-4 response format; item wording is intentionally not copied.'),
        ],
    },
    'co-evolution-theory': {
        'coding': {
            'definition': (
                'Co-evolution requires interdependent populations or organizational '
                'entities whose reciprocal causal changes significantly alter one another\'s '
                'adaptive traits or trajectories.'
            ),
            'constructs': [
                'interdependent entities or populations',
                'adaptive traits and trajectories',
                'reciprocal / multidirectional causality',
                'multilevel embeddedness',
                'variation, selection, and retention',
                'positive feedback',
                'path and history dependence',
            ],
            'mechanisms': [
                'reciprocal adaptation between organizational entities and environments',
                'variation-selection-retention operating interactively across levels',
                'naive selection, managerial selection, hierarchical renewal, and holistic renewal',
                'positive feedback and nonlinear interactions that reinforce system change',
            ],
            'boundary_conditions': [
                'The chapter requires a sufficiently long historical period for dynamic analysis.',
                'The relationship must show reciprocal or multidirectional causality and feedback.',
                'The chapter emphasizes multilevel, embedded, and often geographically proximate systems.',
            ],
            'criticisms': [
                'The chapter says the framework is not yet unified or fully mature.',
                'Nonlinear and multilevel evidence collection makes empirical testing difficult and relatively slow.',
                'Many applications remain conceptual or model-based rather than fully empirical.',
            ],
            'measurement_scales': [
                {
                    'name': 'Coevolution of Institutions and Behaviour',
                    'source': 'Van den Bergh & Stagl (2003)',
                    'metadata': 'Chapter lists four layers and 30 dimensions; treated here as model/operationalization metadata, not a validated scale.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Coevolutionary Model of Agricultural Development',
                    'source': 'Norgaard (1984)',
                    'metadata': 'Model listed in the chapter; no scale items inferred.',
                    'status': 'chapter-reported model metadata',
                },
                {
                    'name': 'Cellular-automata model of interconnected relationship coevolution',
                    'source': 'Sofitra et al. (2015)',
                    'metadata': 'Model application to supply-network relationship strategies.',
                    'status': 'chapter-reported model metadata',
                },
            ],
            'methods': [
                'Longitudinal and dynamic analysis are presented as core design requirements.',
                'Multilevel analysis is used to connect firm, industry, and environment levels.',
                'Cellular-automata simulation and complexity/nonlinear modeling are cited applications.',
            ],
            'cited_works': [
                'Ehrlich & Raven (1964)',
                'Janzen (1980)',
                'Lewin & Volberda (1999)',
                'Volberda & Lewin (2003)',
                'Murmann (2003)',
                'Sofitra et al. (2015)',
            ],
        },
        'evidence': [
            _entry(22, 39, 'definition',
                   'The chapter reviews several definitions and states that the field lacks a single mature, unified definition.'),
            _entry(23, 40, 'definition',
                   'The organizational definition requires two interdependent populations with reciprocal causal influence that changes adaptive traits.'),
            _entry(23, 40, 'boundary_condition',
                   'The chapter emphasizes long historical periods, reciprocal causality, feedback, and geographic or relational proximity.'),
            _entry(24, 41, 'construct',
                   'Five organizational properties are developed: multidirectional causality, multilevel embeddedness, nonlinearity, positive feedback, and path/history dependence.'),
            _entry(24, 41, 'method',
                   'Lewin and Volberda\'s framework links firm, industry, and environment levels with variation, selection, and retention.'),
            _entry(25, 42, 'mechanism',
                   'The chapter lists naive selection, managerial selection, hierarchical renewal, and holistic renewal as co-evolutionary mechanisms.'),
            _entry(26, 43, 'criticism',
                   'The evaluation notes difficult evidence collection, an immature analytical framework, and relatively limited empirical research.'),
            _entry(26, 43, 'measurement',
                   'The chapter lists model/operationalization sources, including a four-layer/30-dimension institutional-behavior model; this is not treated as a validated scale.'),
        ],
    },
    'cognitive-appraisal-theory': {
        'coding': {
            'definition': (
                'Emotion is treated as a response to the meaning assigned to an event '
                'through cognitive appraisal; therefore the same situation can elicit '
                'different emotions for different people.'
            ),
            'constructs': [
                'cognitive appraisal',
                'primary appraisal',
                'secondary appraisal and reappraisal',
                'coping ability and coping',
                'benefit, harm, and threat',
                'stress/anxiety and emotion',
                'problem-focused and emotion-focused coping',
            ],
            'mechanisms': [
                'primary appraisal evaluates relevance, benefit, harm, or threat',
                'secondary appraisal evaluates coping/control resources',
                'problem-focused or emotion-focused coping changes the response state',
                'reappraisal updates meaning and can reduce or sustain activation',
            ],
            'boundary_conditions': [
                'Appraisal is shaped by social context, culture, personal experience, and personality.',
                'The chapter reports disagreement across appraisal models about dimensions and weights.',
                'Decision-tree representations are limited when emotions overlap or appraisals are iterative.',
            ],
            'criticisms': [
                'The chapter reports criticism that emotion is not treated as a basic theoretical construct.',
                'The chapter says the theory gives insufficient attention to emotion effects on cognition and action.',
                'Different appraisal models do not agree on a single dimensional structure.',
            ],
            'measurement_scales': [
                {
                    'name': 'Cognitive Appraisal Scale',
                    'source': 'Skinner & Brewer (2002)',
                    'metadata': '18 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Cognitive Appraisal Scale',
                    'source': 'Folkman & Lazarus (1985)',
                    'metadata': '42 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Cognitive Appraisal Measure',
                    'source': 'Frijda et al. (1989)',
                    'metadata': '19 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'PASA',
                    'source': 'Chapter-listed source',
                    'metadata': 'Primary/secondary appraisal; six dimensions and 16 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; exact source attribution requires primary-source review',
                },
                {
                    'name': 'Cognitive Appraisal Questionnaire',
                    'source': 'Chapter-listed source',
                    'metadata': 'Eight items as listed in the chapter.',
                    'status': 'chapter-reported metadata; exact source attribution requires primary-source review',
                },
            ],
            'methods': [
                'Conceptual appraisal-process diagrams connect primary appraisal, activation, secondary appraisal, and coping.',
                'The chapter provides measurement-source metadata; instrument development and validation must be checked in the cited primary studies.',
            ],
            'cited_works': [
                'Lazarus (1982, 1984, 2006)',
                'Folkman & Lazarus (1985, 1986)',
                'Smith & Ellsworth (1985)',
                'Frijda et al. (1989)',
                'Gratch & Marsella (2004)',
            ],
        },
        'evidence': [
            _entry(29, 46, 'definition',
                   'The chapter opens with Lazarus and frames emotion as a response to the meaning assigned through appraisal.'),
            _entry(30, 47, 'definition',
                   'The chapter explains why one environment can produce different emotions when appraisal-based meaning differs.'),
            _entry(31, 48, 'construct',
                   'Primary appraisal is described using irrelevant, beneficial, or stressful outcomes; secondary appraisal concerns coping/control and later reappraisal.'),
            _entry(32, 49, 'mechanism',
                   'The process diagram links primary appraisal to activation, secondary appraisal to perceived coping ability, and coping type to recovery or sustained stress.'),
            _entry(33, 50, 'boundary_condition',
                   'The chapter compares appraisal dimensions across Arnold, Lazarus, Scherer, and Smith & Ellsworth and notes disagreement about dimensions and weights.'),
            _entry(35, 52, 'criticism',
                   'The evaluation identifies social/cultural and personal constraints on appraisal and discusses criticisms about the role of emotion in the model.'),
            _entry(36, 53, 'measurement',
                   'The chapter lists several appraisal instruments with item counts and primary/secondary dimensions; no item wording is copied.'),
        ],
    },
    'cognitive-dissonance-theory': {
        'coding': {
            'definition': (
                'Inconsistency among cognitions, attitudes, or behavior creates psychological '
                'discomfort and pressure to reduce the inconsistency, especially when the '
                'person sees the behavior as voluntary or consequential.'
            ),
            'constructs': [
                'cognitive consistency/inconsistency',
                'dissonance and consonance',
                'attitude-behavior discrepancy',
                'perceived choice and consequence expectation',
                'effort justification',
                'reward/effort mismatch',
                'self-affirmation and core self-evaluation',
                'organizational commitment escalation',
            ],
            'mechanisms': [
                'induced compliance creates cognition-behavior conflict and justification pressure',
                'free choice among similar alternatives produces post-choice re-evaluation',
                'effort-outcome inconsistency can increase effort justification and satisfaction',
                'choice, threat, expected consequences, and external justification condition reduction',
            ],
            'boundary_conditions': [
                'Voluntary choice and perceived responsibility are central moderators in the chapter examples.',
                'Expected consequences and the size of external reward alter the conflict and reduction response.',
                'The evaluation notes possible cultural and individual differences in dissonance processes.',
            ],
            'criticisms': [
                'The chapter describes dissonance-reduction processes as underdeveloped in the theoretical account.',
                'It notes competing or complementary explanations involving self-perception, self-affirmation, culture, and individual differences.',
            ],
            'measurement_scales': [
                {
                    'name': 'The Dissonance Scale',
                    'source': 'Hausknecht et al. (1998)',
                    'metadata': 'Three dimensions and 81 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'The Dissonance Scale',
                    'source': 'Sweeney et al. (2000)',
                    'metadata': 'Four dimensions and 22 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
            ],
            'methods': [
                'Induced-compliance experiment using a boring task and different external payments.',
                'Free-choice paradigm examining evaluation of similar alternatives after a choice.',
                'Effort-justification initiation experiment comparing a severe versus mild initiation.',
                'The chapter also discusses experiments varying threat, choice, and expected consequences.',
            ],
            'cited_works': [
                'Festinger (1957)',
                'Festinger & Carlsmith (1959)',
                'Brehm (1956)',
                'Linder et al. (1967)',
                'Aronson & Mills (1959)',
                'Cooper (2007)',
                'Harmon-Jones & Harmon-Jones (2007)',
            ],
        },
        'evidence': [
            _entry(39, 56, 'definition',
                   'The chapter introduces Festinger\'s account as a cognitive-consistency theory centered on inconsistency among cognitions, attitudes, and behavior.'),
            _entry(40, 57, 'mechanism',
                   'The theory is described as producing pressure to reduce inconsistency; the induced-compliance example contrasts low and high external payment.'),
            _entry(41, 58, 'boundary_condition',
                   'The chapter explains that choice freedom and the amount of external justification affect whether attitude change and dissonance reduction occur.'),
            _entry(42, 59, 'method',
                   'The chapter reports free-choice and threat-manipulation experiments, including a child forbidden-toy example.'),
            _entry(43, 60, 'method',
                   'Expectation of consequences and effort justification are illustrated through classic experimental paradigms.'),
            _entry(44, 61, 'criticism',
                   'The evaluation discusses cultural and individual differences and competing developments such as self-affirmation.'),
            _entry(44, 61, 'measurement',
                   'Two chapter-listed dissonance scales are recorded by dimensions and item counts only; item wording is not copied.'),
            _entry(45, 62, 'method',
                   'The chapter explicitly groups the classic evidence into induced compliance, free choice, and effort justification paradigms.'),
            _entry(46, 63, 'boundary_condition',
                   'Organizational examples connect dissonance with commitment escalation, decision-making, self-affirmation, and effort-reward mismatch.'),
        ],
    },
    'compensatory-ethics-theory': {
        'coding': {
            'definition': (
                'Moral decisions are treated as temporally connected: prior immoral '
                'behavior can threaten the moral self-image and motivate later moral or '
                'prosocial behavior, whereas prior moral behavior can license later immorality.'
            ),
            'constructs': [
                'prior moral or immoral behavior',
                'moral self-image and moral balance',
                'moral compensation',
                'moral licensing and moral consistency',
                'guilt',
                'moral identity',
                'prosocial behavior',
            ],
            'mechanisms': [
                'prior immorality -> threatened moral image -> pressure to compensate',
                'guilt is described as a mediator between prior immorality and compensation',
                'moral identity and personal traits condition the compensation response',
                'moral consistency and moral compensation/licensing can produce competing predictions',
            ],
            'boundary_conditions': [
                'The chapter distinguishes concern for external reputation from internally held moral self-concept.',
                'Moral responsibility, moral identity, personality, and environmental factors affect which process operates.',
                'The chapter raises possible cultural differences in compensation and moral consistency.',
            ],
            'criticisms': [
                'Replications have produced opposite prosocial-behavior patterns, making compensation difficult to distinguish from consistency.',
                'The chapter calls for better experimental designs and more cross-cultural comparisons.',
            ],
            'measurement_scales': [
                {
                    'name': 'Past-deed recall / moral-behavior priming',
                    'source': 'Jordan et al. (2011)',
                    'metadata': 'Experimental operationalization listed in the chapter; no scale items inferred.',
                    'status': 'chapter-reported operationalization; primary-source verification required',
                },
                {
                    'name': 'Moral-imagery priming and prosocial-behavior tendency',
                    'source': 'Zhong et al. (2010); Ding et al. (2016)',
                    'metadata': 'Experimental operationalizations listed in the chapter; not treated as validated scales.',
                    'status': 'chapter-reported operationalization; primary-source verification required',
                },
            ],
            'methods': [
                'Experimental priming of prior moral or immoral deeds.',
                'Behavioral experiments involving cleansing, volunteering, or prosocial action.',
                'Mediation/moderation designs for guilt and moral identity are reported in a cited study.',
                'Replication and cross-cultural comparison are identified as needed research designs.',
            ],
            'cited_works': [
                'Zhong & Liljenquist (2006)',
                'Zhong et al. (2010)',
                'Jordan et al. (2011)',
                'Gino & Margolis (2011)',
                'Ding et al. (2016)',
                'Joosten et al. (2014)',
                'Hayley & Zinkiewicz (2013)',
            ],
        },
        'evidence': [
            _entry(48, 65, 'definition',
                   'The chapter introduces compensatory ethics through early findings on moral threat, cleansing, and later prosocial behavior.'),
            _entry(49, 66, 'mechanism',
                   'The core account treats moral decisions as a temporal sequence in which prior immorality can damage moral self-image and prompt compensation.'),
            _entry(52, 69, 'mechanism',
                   'Guilt, moral identity, internal control, and personality are discussed as mechanisms or boundary conditions for compensation.'),
            _entry(52, 69, 'boundary_condition',
                   'The chapter contrasts externally evaluated morality with behavior motivated by an internal positive self-concept.'),
            _entry(52, 69, 'criticism',
                   'The evaluation says the dynamic view extends moral-decision research but also reports challenges to the compensation explanation.'),
            _entry(53, 70, 'criticism',
                   'Opposing replication results make moral compensation difficult to separate experimentally from moral consistency or licensing.'),
            _entry(53, 70, 'measurement',
                   'The chapter lists priming and behavioral operationalizations; it does not provide a conventional validated measurement scale.'),
            _entry(54, 71, 'citation',
                   'The chapter lists classic sources including Zhong & Liljenquist, Zhong et al., Jordan et al., Gino & Margolis, and Ding et al.'),
        ],
    },
    'complexity-theory-organizations': {
        'coding': {
            'definition': (
                'Organizational complexity is the emergent diversity, dynamism, variability, '
                'and unpredictability produced by interactions among organizational elements '
                'and levels within changing internal and external environments.'
            ),
            'constructs': [
                'structural complexity',
                'behavioral complexity',
                'cognitive complexity',
                'environmental complexity and uncertainty',
                'self-organization and self-adaptation',
                'emergence and nonlinearity',
                'organizational performance',
            ],
            'mechanisms': [
                'interactions among elements and levels generate emergent system properties',
                'self-organization, self-learning, and positive/negative feedback support adaptation',
                'organizational complexity should be matched to environmental complexity',
                'complexity-performance relationships can be curvilinear rather than monotonic',
            ],
            'boundary_conditions': [
                'Complexity can be analyzed from structural, behavioral, or cognitive perspectives.',
                'The chapter reports different positive and negative effects of complexity on performance.',
                'Measurement depends on organizational units, relations, behavior, goals, strategy, and environmental uncertainty.',
            ],
            'criticisms': [
                'Structural-complexity measurement has not reached consensus.',
                'The chapter says organizational complexity research lacks a unified research paradigm and needs more empirical work.',
                'Traditional linear conceptual and causal models may miss emergent, multilevel, and nonlinear relations.',
            ],
            'measurement_scales': [
                {
                    'name': 'Organizational Complexity Scale',
                    'source': 'Tang (2006)',
                    'metadata': 'Three dimensions and 36 items: structural complexity (13), goal complexity (12), and strategic complexity (11); the chapter reports internal consistency above 0.77.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'NK model',
                    'source': 'Moldoveanu (2004)',
                    'metadata': 'Operationalization using N organizational units and K relations among units; model metadata, not a survey scale.',
                    'status': 'chapter-reported model metadata',
                },
                {
                    'name': 'Structural complexity dimensions',
                    'source': 'Damanpour (1996); Daft (2001)',
                    'metadata': 'Chapter discusses horizontal, vertical, and spatial dimensions; exact operationalization requires primary-source review.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
            ],
            'methods': [
                'Conceptual and causal models alongside empirical organizational research.',
                'Multi-agent simulation and computer simulation for behavioral and cognitive complexity.',
                'Algorithmic/complexity classification and environmental-uncertainty measurement.',
                'The chapter calls for multi-method research and closer empirical engagement with context.',
            ],
            'cited_works': [
                'Damanpour (1996)',
                'Anderson (1999)',
                'Lewin (1999)',
                'Moldoveanu (2004)',
                'Tang (2006)',
                'Ashmos et al. (1996)',
                'Houchin & MacLean (2005)',
            ],
        },
        'evidence': [
            _entry(57, 74, 'definition',
                   'The chapter introduces organizational complexity as a management application of complexity science and identifies Moore as an early representative.'),
            _entry(58, 75, 'definition',
                   'Organizational complexity is linked to diversity, dynamics, variability, unpredictability, and interactions among internal and external elements.'),
            _entry(59, 76, 'construct',
                   'The chapter distinguishes structural, behavioral, and cognitive complexity and describes dimensions used to assess each perspective.'),
            _entry(59, 76, 'measurement',
                   'The chapter discusses horizontal/vertical/spatial structure, the NK model, behavior-based algorithms, multi-agent simulation, and environmental uncertainty.'),
            _entry(60, 77, 'measurement',
                   'Tang\'s organizational complexity scale is described as three dimensions and 36 items, with separate structural, goal, and strategic components.'),
            _entry(60, 77, 'boundary_condition',
                   'The chapter reports positive and negative performance effects and describes a possible curvilinear relationship between complexity and performance.'),
            _entry(61, 78, 'criticism',
                   'The evaluation notes lack of measurement consensus, methodological plurality, and limited empirical testing of organizational complexity.'),
            _entry(61, 78, 'method',
                   'The chapter recommends combining conceptual, empirical, simulation, and context-sensitive methods for complex organizational systems.'),
            _entry(62, 79, 'citation',
                   'The classic-works section includes Anderson, Byrne, Lewin, Mason, Rescher, and other complexity research sources.'),
        ],
    },
    'configural-organization-theory': {
        'coding': {
            'definition': (
                'A holistic view of organizations as internally consistent configurations '
                'of interdependent strategy, structure, leadership, and environmental '
                'attributes, where fit and performance are shaped by nonlinear and dynamic relations.'
            ),
            'constructs': [
                'organizational configuration',
                'internal and external fit',
                'strategy, structure, leadership, and environment',
                'configuration archetype / ideal type',
                'typology and taxonomy',
                'dynamic stability and punctuated equilibrium',
                'equifinality',
                'organizational performance',
            ],
            'mechanisms': [
                'holistic interaction among organizational attributes rather than isolated-variable effects',
                'nonlinear and bidirectional causal relations within a configuration',
                'punctuated transitions between relatively stable configurations',
                'theory-led typology and data-led taxonomy identify alternative configurations',
                'multiple configurations can reach similar outcomes through equifinality',
            ],
            'boundary_conditions': [
                'The chapter emphasizes longitudinal and historical dependence during organizational change.',
                'Internal and external fit may be difficult when environmental demands conflict.',
                'The appropriate degree of configuration depends on environmental uncertainty and change.',
            ],
            'criticisms': [
                'The chapter reports weak or contested evidence linking strategic clusters to performance.',
                'It notes inconsistent measures, methodological limits, and limited cross-industry comparison.',
                'Simultaneously achieving internal and external fit may be theoretically and practically difficult.',
            ],
            'measurement_scales': [
                {
                    'name': 'Measurement of Organizational Archetypes',
                    'source': 'Miller & Friesen (1977)',
                    'metadata': 'Five dimensions and 14 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Environment, Structure, and Strategy-making Configuration',
                    'source': 'Miller & Friesen (1980)',
                    'metadata': 'Three dimensions and 24 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Measurement of Ideal Configurations',
                    'source': 'Doty, Glick, & Huber (1993)',
                    'metadata': 'Study 1: five dimensions/15 items; Study 2: four dimensions/10 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'HR Configurations Scale',
                    'source': 'Youndt & Snell (2004)',
                    'metadata': 'Six dimensions and 34 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Marketing configuration-performance',
                    'source': 'Vorhies & Morgan (2003)',
                    'metadata': 'Ten dimensions and 32 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
            ],
            'methods': [
                'Conceptual typology: theory-led, a priori classification into ideal types.',
                'Empirical taxonomy: data-driven grouping using similarity, clustering, and hypothesis tests.',
                'Longitudinal designs are used to study dynamic stability and configuration change.',
                'Meta-analysis and fit/performance tests are cited applications.',
            ],
            'cited_works': [
                'Miller (1982, 1986, 1987)',
                'Meyer et al. (1993)',
                'Doty et al. (1993)',
                'Ketchen et al. (1993, 1997)',
                'Siggelkow (2002)',
                'Fiss (2007)',
                'Short et al. (2008)',
            ],
        },
        'evidence': [
            _entry(64, 81, 'definition',
                   'The chapter traces organizational configuration to Miller and presents it as a major idea in organization and strategy research.'),
            _entry(65, 82, 'definition',
                   'Configuration thinking extends contingency logic by treating strategy, structure, and context as an interdependent holistic pattern.'),
            _entry(66, 83, 'mechanism',
                   'The chapter describes nonlinear, bidirectional relations and configuration attributes that can change roles over time.'),
            _entry(67, 84, 'method',
                   'Typology is theory-led and a priori; taxonomy is empirically driven and uses similarity, clustering, and hypothesis-testing techniques.'),
            _entry(67, 84, 'boundary_condition',
                   'Configuration research emphasizes longitudinal designs, time dependence, and history dependence rather than only cross-sectional equilibrium.'),
            _entry(69, 86, 'criticism',
                   'The evaluation reports contested cluster-performance evidence, measurement inconsistency, methodological limits, and weak cross-industry comparison.'),
            _entry(70, 87, 'measurement',
                   'The chapter lists five configuration instruments with dimensions and item counts; item wording is intentionally not copied.'),
        ],
    },
    'conservation-of-resources': {
        'coding': {
            'definition': (
                'Individuals strive to obtain, retain, cultivate, and protect valued resources; '
                'threatened or actual loss, or failed resource gain after investment, produces stress '
                'and motivates resource-protection or resource-acquisition behavior.'
            ),
            'constructs': [
                'object, condition, personal-characteristic, and energy resources',
                'resource loss and resource gain',
                'resource investment',
                'resource caravans and caravan passageways',
                'initial resource effect',
                'resource loss and gain spirals',
                'stress, burnout, and recovery',
                'crossover of resources and strain',
            ],
            'mechanisms': [
                'primacy of resource loss',
                'resource investment to prevent loss, recover, or acquire resources',
                'gain paradox and resource desperation under low-resource conditions',
                'resource caravans interact with ecological/caravan-passageway conditions',
                'initial resources shape later loss resistance and gain capacity',
                'loss spirals are stronger/faster than gain spirals; resources can cross over between people',
            ],
            'boundary_conditions': [
                'Resource value is partly subjective and depends on goals, culture, and context.',
                'Resource dynamics unfold over time and within organizational or cultural ecologies.',
                'Initial resource levels and available environmental support condition loss and gain processes.',
            ],
            'criticisms': [
                'The chapter identifies continuing problems in defining and measuring the core resource construct.',
                'Many designs do not fully represent the theory\'s dynamic resource processes.',
                'The temporal development of loss/gain spirals remains incompletely specified.',
            ],
            'measurement_scales': [
                {
                    'name': 'Conservation of Resources Evaluation',
                    'source': 'Hobfoll, Lilly, & Jackson (1991)',
                    'metadata': 'No dimensions distinguished; 74 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Perceived Resources Scale',
                    'source': 'Hochwarter et al. (2007)',
                    'metadata': 'No dimensions distinguished; six items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
            ],
            'methods': [
                'Dynamic and longitudinal designs for resource loss/gain processes.',
                'Crossover or multilevel designs for interpersonal resource and strain transmission.',
                'Resource inventories and perceived-resource measures are cited operationalizations.',
                'The chapter cites organizational applications to stress, work-family conflict, burnout, and engagement.',
            ],
            'cited_works': [
                'Hobfoll (1989, 2001a, 2001b, 2011)',
                'Halbesleben et al. (2014)',
                'Hobfoll et al. (2018)',
                'Grandey & Cropanzano (1999)',
                'Demerouti et al. (2004)',
                'Hakanen et al. (2011)',
                'Hochwarter et al. (2007)',
            ],
        },
        'evidence': [
            _entry(73, 90, 'definition',
                   'The chapter introduces COR as a stress theory centered on preserving, protecting, and acquiring resources.'),
            _entry(74, 91, 'mechanism',
                   'Stress is linked to threatened loss, actual loss, or failed gain after effort; individuals invest current resources to limit net loss.'),
            _entry(75, 92, 'construct',
                   'The chapter distinguishes object, condition, personal-characteristic, and energy resources and discusses subjective resource value.'),
            _entry(76, 93, 'mechanism',
                   'The revised COR framework is summarized with a basic tenet, five principles, and three corollaries, including loss/gain spirals.'),
            _entry(77, 94, 'mechanism',
                   'Primacy of loss, resource investment, gain paradox, and resource desperation are explained as distinct principles.'),
            _entry(78, 95, 'construct',
                   'Resource caravans, caravan passageways, initial resource effect, and loss/gain spirals extend the core resource model.'),
            _entry(79, 96, 'boundary_condition',
                   'The chapter emphasizes ecological context, time, resource interaction, and crossover between people in teams or organizations.'),
            _entry(80, 97, 'criticism',
                   'The evaluation identifies unresolved definition/measurement issues and limited representation of dynamic resource change.'),
            _entry(80, 97, 'measurement',
                   'Two resource measures are listed with item counts only; item wording is intentionally not copied.'),
        ],
    },
    'construal-level-theory': {
        'coding': {
            'definition': (
                'Responses depend on the abstraction of a mental representation (construal level), '
                'which is related bidirectionally to psychological distance; high construal is abstract '
                'and goal/value focused, whereas low construal is concrete and feasibility focused.'
            ),
            'constructs': [
                'construal level',
                'abstract and concrete mental representation',
                'temporal, spatial, social, and hypothetical distance',
                'feasibility and desirability',
                'construal-distance fit',
                'motivation and goals',
                'ethics, innovation, leadership, and role integration',
            ],
            'mechanisms': [
                'psychological distance activates higher-level construal',
                'higher-level construal can make distant goals seem clearer or more attainable',
                'fit between construal level and distance or incentive framing changes motivation',
                'abstract/concrete communication aligns with hierarchical distance and task needs',
            ],
            'boundary_conditions': [
                'The theory distinguishes temporal, spatial, social, and probability-based distance.',
                'Power, hierarchy, virtual work, and remote work are organizational contexts discussed in the chapter.',
                'The chapter says the boundary between construal level, its manifestations, and antecedents remains unclear.',
            ],
            'criticisms': [
                'Constructs and antecedents are often conflated across studies.',
                'The chapter says the application boundary is not yet clear and can make the theory appear overly general.',
                'Most studies use experimental manipulations, while relatively few use direct scales.',
            ],
            'measurement_scales': [
                {
                    'name': 'Workplace Construal Level',
                    'source': 'Reyt & Wiesenfeld (2015)',
                    'metadata': 'One dimension and 18 items; high/low construal anchors follow each workplace activity as described in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
            ],
            'methods': [
                'Temporal-distance manipulation: imagine completing a task in one year versus tomorrow.',
                'Spatial-distance manipulation: near versus far locations.',
                'Global-versus-local representation manipulation using maps.',
                'Feasibility/how versus desirability/why framing and workplace scale measurement.',
            ],
            'cited_works': [
                'Liberman & Trope (1998, 2008)',
                'Trope & Liberman (2000, 2003, 2010)',
                'Fujita et al. (2006)',
                'Trope et al. (2007)',
                'Wiesenfeld et al. (2017)',
                'Reyt & Wiesenfeld (2015)',
            ],
        },
        'evidence': [
            _entry(83, 100, 'definition',
                   'The chapter traces construal-level theory to temporal construal theory and its expansion to multiple psychological distances.'),
            _entry(84, 101, 'definition',
                   'Construal level is presented as the abstraction of mental representation, with high levels emphasizing goals/values and low levels emphasizing concrete feasibility.'),
            _entry(85, 102, 'mechanism',
                   'Temporal, spatial, social, and probability distance are linked to higher construal; the relation is described as bidirectional.'),
            _entry(86, 103, 'boundary_condition',
                   'The chapter applies construal level to ethics, innovation/change, learning-source choice, and employee voice, while noting mixed ethical findings.'),
            _entry(87, 104, 'boundary_condition',
                   'Hierarchy, power, virtual organization, and remote work are discussed as organizational contexts that change psychological distance.'),
            _entry(87, 104, 'criticism',
                   'The evaluation identifies unclear distinctions among construal level, its manifestations, and antecedents, as well as unclear application boundaries.'),
            _entry(88, 105, 'method',
                   'The chapter lists temporal, spatial, global/local, and feasibility/desirability experimental manipulations.'),
            _entry(89, 106, 'measurement',
                   'The workplace construal-level measure is recorded as one dimension and 18 items; item wording is intentionally not copied.'),
        ],
    },
    'contingency-theory': {
        'coding': {
            'definition': (
                'There is no single best organizational design or management method; '
                'effective structure and management depend on the fit among strategy, '
                'technology, size, environment, tasks, and other contextual factors.'
            ),
            'constructs': [
                'contingency variables',
                'organizational structure',
                'environmental and task uncertainty',
                'differentiation and integration',
                'fit and misfit',
                'performance',
                'structural adaptation / SARFIT',
                'configuration, complementarity, and complexity',
            ],
            'mechanisms': [
                'if a contextual condition exists, a more suitable management arrangement can be selected',
                'misfit lowers performance and triggers structural adaptation to regain fit',
                'internal and external fit are pursued together and may be constrained by conflict',
                'complementary elements jointly increase the value of organizational choices',
                'NK(C), frontier, conditional mean/variance, and tail analyses model complex fit',
            ],
            'boundary_conditions': [
                'The appropriate arrangement depends on environmental, task, technological, and member requirements.',
                'Multiple contingency factors can conflict, so internal and external fit may require trade-offs.',
                'The chapter emphasizes dynamic change and adaptation rather than a static equilibrium only.',
            ],
            'criticisms': [
                'The chapter reports criticism that contingency research emphasizes outcomes/content over dynamic process.',
                'Many studies examine isolated contingency factors without sufficient integration.',
                'Organization-design research can overlook how work is actually performed.',
            ],
            'measurement_scales': [],
            'methods': [
                'Lawrence and Lorsch study of six firms in the same industry and environment.',
                'Cross-national empirical research used to develop the SARFIT model.',
                'Configuration, complementarity, and complexity analyses, including NK(C) modeling.',
                'Frontier analysis, joint conditional mean/variance estimation, and distribution-tail analysis.',
            ],
            'cited_works': [
                'Lawrence & Lorsch (1967, 1969, 1970)',
                'Luthans (1973)',
                'Luthans et al. (1976)',
                'Donaldson (1987, 2001)',
                'Drazin & Van de Ven (1985)',
                'Van de Ven et al. (2013)',
            ],
        },
        'evidence': [
            _entry(91, 108, 'definition',
                   'The chapter introduces contingency theory as a response to the idea of one best management method and links fit to contextual factors.'),
            _entry(92, 109, 'definition',
                   'Luthans\' framework is described as matching quantitative, behavioral, and systems approaches with relevant situational factors.'),
            _entry(93, 110, 'mechanism',
                   'Lawrence and Lorsch link environmental uncertainty to differentiation/integration; Luthans\' model expresses an if-then relation rather than simple causation.'),
            _entry(94, 111, 'mechanism',
                   'SARFIT describes misfit lowering performance, triggering structural adaptation, regaining fit, and restoring performance.'),
            _entry(95, 112, 'boundary_condition',
                   'Configuration, complementarity, and complexity perspectives address multiple, sometimes conflicting, contingency factors and the possibility of equifinality.'),
            _entry(96, 113, 'mechanism',
                   'Complementarity requires system-level adjustment because changing one element in isolation can reduce performance.'),
            _entry(97, 114, 'method',
                   'The chapter lists NK(C), frontier, joint estimation, and tail-analysis approaches for quantifying complex fit and adaptation.'),
            _entry(97, 114, 'criticism',
                   'The evaluation recognizes the value of situational fit but notes process, integration, and work-activity gaps in existing research.'),
            _entry(98, 115, 'citation',
                   'The classic-works section includes Donaldson, Lawrence & Lorsch, Luthans, and Van de Ven sources.'),
        ],
    },
    'co-opetition-theory': {
        'coding': {
            'definition': (
                'Co-opetition describes firms or organizations simultaneously cooperating '
                'and competing, with cooperation often supporting value creation and competition '
                'shaping value capture or distribution.'
            ),
            'constructs': [
                'cooperation',
                'competition',
                'co-opetition relationship and balance',
                'goal structure and mutual dependence',
                'value creation and value appropriation',
                'resource complementarity',
                'knowledge acquisition and leakage',
                'innovation and performance',
            ],
            'mechanisms': [
                'positive interdependence supports cooperation; negative interdependence supports competition',
                'firms cooperate in value creation and compete in value distribution',
                'co-opetition evolves over time and can shift from competition to balance to cooperation',
                'value-chain position, dependence, conflict resolution, and communication shape the relationship',
                '2x2 cooperation-by-competition typologies distinguish relationship forms',
            ],
            'boundary_conditions': [
                'The relationship depends on mutual dependence, relative position, cultural fit, responsibilities, and conflict-resolution mechanisms.',
                'External conditions include industry concentration, size, resource availability, regulation, and internationalization.',
                'Internal conditions include ownership, specialized asset investment, power asymmetry, and self-protection.',
                'Cooperation may be stronger farther from consumers in the value chain, while competition may be stronger near consumers.',
            ],
            'criticisms': [
                'The chapter reports few mature, widely accepted scales and substantial reliance on reviews and theoretical derivation.',
                'Interaction mechanisms and environmental effects are not sufficiently analyzed.',
                'Performance effects may involve moderators and mediators rather than a simple positive association.',
            ],
            'measurement_scales': [
                {
                    'name': 'Cross-functional Coopetition Scale',
                    'source': 'Luo, Slotegraaf, & Pan (2006)',
                    'metadata': 'Three dimensions and 23 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Coopetition Scale',
                    'source': 'Garcia & Velasco (2002)',
                    'metadata': 'Five dimensions as listed in the chapter; item count is not supplied there.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Alliance-firm co-opetition intensity indicators',
                    'source': 'Li & Jin (2008)',
                    'metadata': 'Two dimensions and seven items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
            ],
            'methods': [
                'Game-theoretic modeling of value creation and value capture.',
                'Comparative case studies of firms in Finland and Sweden.',
                'Empirical study of 73 European biotechnology firms.',
                '2x2 classification of cooperation and competition levels.',
            ],
            'cited_works': [
                'Deutsch (1949)',
                'Brandenburger & Nalebuff (1996)',
                'Bengtsson & Kock (1999, 2000)',
                'Luo (2005, 2007)',
                'Luo et al. (2006)',
                'Garcia et al. (2002)',
                'Zineldin (2004)',
            ],
        },
        'evidence': [
            _entry(100, 117, 'definition',
                   'The chapter traces co-opetition from Deutsch\'s cooperation-competition work and the 1996 Brandenburger and Nalebuff book.'),
            _entry(101, 118, 'construct',
                   'Three goal structures are distinguished: individualistic, competitive, and cooperative; organizational co-opetition combines competition and cooperation.'),
            _entry(102, 119, 'mechanism',
                   'Game theory is used to distinguish cooperation in value creation from competition in value capture; co-opetition can evolve across time and value-chain positions.'),
            _entry(102, 119, 'boundary_condition',
                   'Mutual dependence, cultural fit, responsibility clarity, conflict resolution, communication, and internal/external industry conditions shape co-opetition.'),
            _entry(103, 120, 'construct',
                   'The chapter covers firm-competitor, multinational-subsidiary, channel, and within-firm departmental co-opetition and uses 2x2 relationship types.'),
            _entry(103, 120, 'criticism',
                   'The evaluation notes a shortage of mature scales and limited analysis of interaction mechanisms and environment.'),
            _entry(104, 121, 'measurement',
                   'Three co-opetition measurement sources are listed with dimensions/items where supplied; item wording is not copied.'),
        ],
    },
    'dual-system-theory': {
        'coding': {
            'definition': (
                'Decision making is modeled as the interaction of a fast, automatic, '
                'heuristic/impulsive System 1 and a slower, effortful, reflective/analytic '
                'System 2; the systems can cooperate or conflict.'
            ),
            'constructs': [
                'System 1 / heuristic or impulsive processing',
                'System 2 / analytic or reflective processing',
                'central and peripheral routes',
                'attention and self-control',
                'cognitive reflection',
                'decision quality and rationality',
                'temporal choice and delay of gratification',
            ],
            'mechanisms': [
                'System 1 activates quickly; System 2 can take over when additional analysis is needed',
                'conflicting directions produce S-criterion problems and heuristic dominance',
                'attention, effort, involvement, and self-control enable analytic processing',
                'time horizon and self-control shift which system dominates intertemporal choice',
                'ego depletion and energy claims are presented as conditions affecting System 2 activation',
            ],
            'boundary_conditions': [
                'Processing depends on task complexity, time pressure, involvement, information-processing ability, and self-control.',
                'Different dual-system models use related but non-identical terms and may imply different boundaries.',
                'Unconscious processing may outperform conscious analysis on complex tasks but not simple tasks, as the chapter reports.',
            ],
            'criticisms': [
                'The chapter reports ambiguity in defining the two systems and disagreement about whether two systems are necessary.',
                'Evidence for a strict dual architecture is contested by multi-channel and single-channel accounts.',
                'Analytic processing is not always superior; task complexity and expertise can favor intuition.',
            ],
            'measurement_scales': [
                {
                    'name': 'Need for Cognition Scale',
                    'source': 'Cacioppo & Petty (1982)',
                    'metadata': 'One dimension and 18 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Cognitive Reflection Test',
                    'source': 'Frederick (2005)',
                    'metadata': 'One dimension and three items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Stroop Effect task',
                    'source': 'MacLeod (1991)',
                    'metadata': 'Experimental task used as an operationalization of processing conflict; no item scale inferred.',
                    'status': 'chapter-reported operationalization',
                },
            ],
            'methods': [
                'S-criterion Linda problem for heuristic versus probability-rule conflict.',
                'Stroop task for automatic interference and controlled attention.',
                'Intertemporal movie-choice task varying immediate versus delayed framing.',
                'Delay-of-gratification, cognitive reflection, and neurocognitive evidence are cited applications.',
            ],
            'cited_works': [
                'Evans (1984, 2008)',
                'Petty & Cacioppo (1984, 1986)',
                'Stanovich & West (2000)',
                'Kahneman (2011)',
                'Strack & Deutsch (2004)',
                'Kruglanski & Gigerenzer (2011)',
                'Evans & Stanovich (2013)',
            ],
        },
        'evidence': [
            _entry(107, 124, 'definition',
                   'The chapter surveys dual-system terminology from heuristic/analytic and central/peripheral routes to System 1/System 2.'),
            _entry(108, 125, 'definition',
                   'System 1 is described as fast, automatic, and low-effort; System 2 as slower, conscious, effortful, and rule/information based.'),
            _entry(109, 126, 'mechanism',
                   'The chapter compares heuristic/analytic, central/peripheral, reflective/impulsive, and System 1/System 2 models.'),
            _entry(110, 127, 'mechanism',
                   'System 1 usually initiates; System 2 can take over when the problem requires more analysis, and the systems may give conflicting directions.'),
            _entry(111, 128, 'method',
                   'The Linda problem and Stroop task are presented as classic conflict demonstrations.'),
            _entry(112, 129, 'method',
                   'An intertemporal movie-choice task shows that immediate versus delayed framing changes the dominant processing mode.'),
            _entry(113, 130, 'criticism',
                   'The evaluation reports competing accounts of system boundaries, evidence for dual systems, and the quality of analytic versus intuitive decisions.'),
            _entry(114, 131, 'measurement',
                   'The chapter lists cognitive-need, cognitive-reflection, and Stroop operationalizations; item wording is not copied.'),
        ],
    },
    'ego-depletion-theory': {
        'coding': {
            'definition': (
                'Prior acts of self-control temporarily reduce the ability or willingness '
                'to perform later self-control because self-control activities draw on a '
                'limited, shared resource; recovery can restore the capacity.'
            ),
            'constructs': [
                'ego depletion / state depletion',
                'self-control and self-regulation',
                'limited self-regulatory resource or energy',
                'motivation and attention',
                'sleep deprivation and recovery',
                'emotional labor and work demands',
                'work engagement, deviance, and counterproductive behavior',
            ],
            'mechanisms': [
                'prior control, choice, inhibition, or emotion regulation -> resource depletion',
                'depletion reduces later self-control and increases reliance on intuition or immediate rewards',
                'individual motivation, traits, and organizational conditions can resist or amplify depletion',
                'employee or supervisor depletion can mediate cross-level and downstream behavior',
                'daily sleep and work events produce within-person fluctuations in depletion',
            ],
            'boundary_conditions': [
                'Trait self-control, motivation, religion, reasoning ability, and self-regulatory capacity can buffer depletion.',
                'Sleep loss, discrimination-related effort, long hours, interruptions, emotional labor, temptation, and abusive supervision can increase depletion.',
                'The chapter emphasizes within-person dynamics and daily tracking in organizational research.',
            ],
            'criticisms': [
                'The resource or energy itself has no direct measure; most studies infer depletion from task performance.',
                'Psychological fatigue, motivation, and negative affect may confound or mediate the proposed effect.',
                'Research has focused on short-term negative outcomes more than long-term or possible positive effects.',
                'The glucose account is reported as contested rather than settled evidence.',
            ],
            'measurement_scales': [
                {
                    'name': 'Shirom-Melamed Burnout Measure',
                    'source': 'Shirom & Melamed (2006)',
                    'metadata': 'Two dimensions and 12 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'State Self-Control Capacity Scale',
                    'source': 'Twenge, Muraven, & Tice (2004)',
                    'metadata': '25 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Self-regulation Impairment Scale',
                    'source': 'Thau & Mitchell (2011)',
                    'metadata': 'Seven items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Morning State-depletion Scale',
                    'source': 'Lanaj, Johnson, & Barnes (2014)',
                    'metadata': 'Five items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'State Self-control Capacity Scale',
                    'source': 'Welsh et al. (2014)',
                    'metadata': 'Five items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Depletion Scale',
                    'source': 'Lin, Ma, & Johnson (2016)',
                    'metadata': 'Five items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Subjective Depletion Feeling Scale',
                    'source': 'Trougakos et al. (2015)',
                    'metadata': 'Three items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Resource Depletion Scale',
                    'source': 'Lee et al. (2016)',
                    'metadata': 'Ten items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
            ],
            'methods': [
                'Daily longitudinal tracking of leaders and subordinates over 10 workdays.',
                'Daily longitudinal tracking over four workdays for subordinate deviance and supervisor depletion.',
                'Self-control and self-regulation tasks are used as indirect depletion operationalizations.',
                'Organizational mediation models connect employee, supervisor, sleep, and work-behavior variables.',
            ],
            'cited_works': [
                'Baumeister et al. (1998)',
                'Baumeister, Vohs, & Tice (2007)',
                'Hagger et al. (2010)',
                'Inzlicht & Schmeichel (2012)',
                'Christian & Ellis (2011)',
                'Lanaj et al. (2014)',
                'Mawritz et al. (2017)',
            ],
        },
        'evidence': [
            _entry(117, 134, 'definition',
                   'The chapter traces ego depletion to Baumeister\'s limited-resource account of self-control.'),
            _entry(118, 135, 'definition',
                   'Ego depletion is described as a temporary reduction in later self-control capacity or willingness after prior self-control activity.'),
            _entry(118, 135, 'mechanism',
                   'The strength model lists shared, limited, temporarily recoverable resources used across different self-control activities.'),
            _entry(119, 136, 'construct',
                   'Self-control, emotion regulation, attention, decision making, and impulse control are described as resource-demanding activities.'),
            _entry(120, 137, 'boundary_condition',
                   'Sleep, discrimination-related effort, autonomy, rewards, long hours, interruptions, emotional labor, and workplace temptation are discussed as organizational conditions.'),
            _entry(121, 138, 'method',
                   'Daily tracking studies are reported: one follows leaders for 10 workdays and another follows subordinates/supervisors for four workdays.'),
            _entry(121, 138, 'criticism',
                   'The evaluation notes that the resource is inferred indirectly and that depletion effects may be confounded with fatigue, motivation, or negative affect.'),
            _entry(122, 139, 'measurement',
                   'Eight chapter-listed depletion, self-control, burnout, and resource measures are recorded by metadata only; item wording is not copied.'),
            _entry(123, 140, 'citation',
                   'The classic-works section includes Baumeister et al., Hagger et al., Inzlicht & Schmeichel, and organizational applications.'),
        ],
    },
    'emotional-contagion-theory': {
        'coding': {
            'definition': (
                'Emotional contagion is interpersonal transmission and convergence of affect, '
                'often beginning with automatic mimicry and feedback but also involving conscious '
                'emotional comparison, empathy, and perspective-taking.'
            ),
            'constructs': [
                'primitive/implicit emotional contagion',
                'conscious/explicit emotional contagion',
                'mimicry and feedback',
                'emotional convergence and synchronization',
                'emotional susceptibility and empathy',
                'interpersonal and group emotion',
                'organizational culture and climate',
            ],
            'mechanisms': [
                'perception -> facial/vocal/postural mimicry -> feedback -> affective convergence',
                'conscious contagion uses emotional comparison, empathy, and perspective-taking',
                'interpersonal contagion aggregates into team emotion through shared events and convergence',
                'leader, employee, and customer emotions can transmit bidirectionally across relationships',
                'multilevel and social-network processes connect individual emotion to group climate',
            ],
            'boundary_conditions': [
                'Gender socialization, empathy, interdependent self, age, commitment, and susceptibility shape contagion strength.',
                'Group size, familiarity, shared events, team interdependence, stability, power, status, and culture condition group contagion.',
                'Positive and negative contagion may be asymmetric, and duration and direction can differ by sender/receiver.',
            ],
            'criticisms': [
                'Some customer-service findings do not support a simple automatic primitive-contagion effect.',
                'The evaluation calls for clearer mechanisms distinguishing positive and negative contagion.',
                'Duration and bidirectionality remain underexamined, especially in employee-customer and leader-employee relations.',
                'Higher-level culture/climate effects need multilevel and social-network evidence.',
            ],
            'measurement_scales': [
                {
                    'name': 'Emotional Contagion Scale',
                    'source': 'Doherty (1997)',
                    'metadata': 'Five dimensions and 15 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Susceptibility to Emotional Contagion Scale',
                    'source': 'Siebert, Siebert, & Taylor-McLaughlin (2007)',
                    'metadata': 'One dimension and five items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Emotional Contagion at Work Scale',
                    'source': 'Petitta & Naughton (2015)',
                    'metadata': 'Two dimensions and 29 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Job Affect Scale',
                    'source': 'Burke et al. (1989)',
                    'metadata': 'Two dimensions and 20 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
            ],
            'methods': [
                'Within-person, between-person, interpersonal, group/team, and organizational-level analysis.',
                'Employee-customer and leader-employee interaction studies.',
                'Multilevel analysis and social-network analysis are proposed for higher-level effects.',
                'Individual-difference and team-convergence operationalizations are cited applications.',
            ],
            'cited_works': [
                'Hatfield et al. (1992, 1993, 1994)',
                'Barsade (2002)',
                'Barger & Grandey (2006)',
                'Totterdell (2000)',
                'Tee (2015)',
                'Pugh (2001)',
                'Doherty et al. (1995, 1997)',
            ],
        },
        'evidence': [
            _entry(126, 143, 'definition',
                   'The chapter traces emotional contagion to Hatfield and describes its expansion from primitive contagion to conscious and group processes.'),
            _entry(127, 144, 'definition',
                   'Emotional contagion is described as automatic mimicry and synchronization of expressions, voices, postures, and actions that can produce emotional convergence.'),
            _entry(127, 144, 'mechanism',
                   'The within-person account uses a mimicry-feedback mechanism in which observed behavior and feedback influence the observer\'s affect.'),
            _entry(128, 145, 'boundary_condition',
                   'The chapter distinguishes subconscious primitive contagion from conscious emotional comparison using empathy and perspective-taking.'),
            _entry(129, 146, 'construct',
                   'Individual differences, employee-customer contagion, and leader-employee contagion are analyzed across interpersonal relationships.'),
            _entry(130, 147, 'mechanism',
                   'Group emotion is described as emerging through shared events, interpersonal influence, emotional convergence, and synchronization.'),
            _entry(131, 148, 'method',
                   'The chapter proposes multilevel and social-network analysis for linking individual contagion to group and organizational climate.'),
            _entry(131, 148, 'criticism',
                   'The evaluation notes asymmetric positive/negative effects, unresolved duration, and the need to study bidirectional contagion.'),
            _entry(132, 149, 'measurement',
                   'Four chapter-listed emotional-contagion/affect measures are recorded by dimensions and item counts only; item wording is not copied.'),
        ],
    },
    'emotion-as-social-information-theory': {
        'coding': {
            'definition': (
                'Emotion-as-social-information theory (EASI) treats expressed emotion as '
                'a social signal that can influence another person through an affective '
                'reaction route or a cognitive-inference route.'
            ),
            'constructs': [
                'emotional expressions and displays',
                'observer affective reaction',
                'cognitive inferential process',
                'emotional contagion and affect infusion',
                'social information about state, intent, goals, and evaluation',
                'epistemic motivation / information-processing depth',
                'dyadic, team, and organizational interaction outcomes',
            ],
            'mechanisms': [
                'emotion expression -> affective reaction/emotional contagion -> judgment and behavior',
                'emotion expression -> inference about the expresser or situation -> adaptive response',
                'emotion-induced affect can enter decision making through affect infusion and attribution',
                'social context and individual information-processing depth condition the two routes',
            ],
            'boundary_conditions': [
                'Expression intensity, authenticity, appropriateness, and the social context condition its effects.',
                'Epistemic motivation and information-processing depth can shift reliance between affective reaction and inference.',
                'Emotion category and positive/negative asymmetry may produce different influence patterns.',
                'Status and relationship context are relevant in leader-follower, employee-customer, and negotiation settings.',
            ],
            'criticisms': [
                'The chapter reports that applications remain concentrated in experiments and that a complete questionnaire is not yet available.',
                'Asymmetry across emotions, directionality, and effects of emotions beyond happiness and anger require further evidence.',
                'The model needs additional validation before broad management-practice claims are made.',
            ],
            'measurement_scales': [
                {
                    'name': 'Affective Reaction Measure',
                    'source': 'Van Kleef et al. (2009)',
                    'metadata': 'One dimension and six items as listed in the chapter; item wording is not copied.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Inferential Process Measure',
                    'source': 'Van Kleef et al. (2009)',
                    'metadata': 'One dimension and five items as listed in the chapter; item wording is not copied.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
            ],
            'methods': [
                'Experimental studies of emotional displays, affective reactions, and inferences.',
                'Dyadic negotiation and interpersonal interaction designs.',
                'Leader-follower and team-performance studies, including epistemic-motivation moderation.',
                'The chapter calls for broader survey, multilevel, and organizational applications.',
            ],
            'cited_works': [
                'Van Kleef (2009, 2014)',
                'Van Kleef, De Dreu, & Manstead (2010)',
                'Van Kleef, Homan, & Cheshin (2012)',
                'Van Kleef & Côté (2017)',
                'Homan, Van Kleef, & Sanchez-Burks (2016)',
                'Van Kleef, Van Doorn, Heerdink, & Koning (2011)',
            ],
        },
        'evidence': [
            _entry(135, 152, 'definition',
                   'The chapter introduces EASI through Van Kleef and frames emotion as a social signal that can influence interpersonal cognition, attitudes, and behavior.'),
            _entry(136, 153, 'mechanism',
                   'The model distinguishes an affective-reaction route and a cognitive-inference route, with social context and information-processing depth as boundary conditions.'),
            _entry(137, 154, 'mechanism',
                   'The affective route is linked to mimicry, emotional contagion, affect infusion, attribution, memory, and subsequent decisions or cooperation.'),
            _entry(138, 155, 'mechanism',
                   'The inference route treats expressed emotion as information about the expresser\'s state, intentions, goals, and evaluation of a task or situation.'),
            _entry(139, 156, 'boundary_condition',
                   'The chapter discusses appropriateness, intensity, and authenticity of emotional expressions as conditions shaping observer responses.'),
            _entry(140, 157, 'boundary_condition',
                   'The discussion uses emotional asymmetry and emotion category to explain why effects of anger, happiness, disappointment, and guilt need not be identical.'),
            _entry(140, 157, 'method',
                   'Cited applications include negotiation, leader emotional displays, follower creativity or analysis, and team cooperation; the chapter characterizes the evidence as mainly experimental.'),
            _entry(141, 158, 'measurement',
                   'The chapter lists separate one-dimensional affective-reaction and inferential-process measures with six and five items; item wording is not copied.'),
            _entry(142, 159, 'criticism',
                   'The management implications are presented as conditional guidance because the model lacks a broadly established survey instrument and needs context-sensitive application.'),
        ],
    },
    'ethical-leadership-theory': {
        'coding': {
            'definition': (
                'Ethical leadership is presented as a leadership style in which leaders model '
                'appropriate conduct, communicate ethical standards, use reinforcement and '
                'fair decision processes, and influence followers\' moral behavior.'
            ),
            'constructs': [
                'ethical person / moral person',
                'ethical manager / moral manager',
                'role modeling and visible ethical action',
                'care, respect, service, and people orientation',
                'ethical standards, responsibility, and fair/open decisions',
                'moral cognition and ethical awareness',
                'ethical climate and follower moral behavior',
            ],
            'mechanisms': [
                'ethical role modeling and social learning shape follower conduct',
                'two-way communication and reinforcement transmit ethical standards',
                'social exchange and psychological safety/meaning explain employee outcomes',
                'ethical climate and trickle-down leadership transmit effects across levels',
                'ethical leadership can increase prosocial behavior and reduce counterproductive or deviant behavior',
            ],
            'boundary_conditions': [
                'Leader traits, moral reasoning, locus of control, Machiavellianism, and social responsibility are cited antecedents.',
                'Moral situation, moral intensity, role modeling, power distance, autonomy, performance pressure, and interpersonal conflict condition ethical leadership.',
                'Employee age, psychological empowerment, implicit theories, LMX, and leader role-modeling strength moderate some outcomes.',
                'Cultural context affects the dimensions and structure of the construct and its measures.',
            ],
            'criticisms': [
                'The chapter notes disagreement and ambiguity in the definition of ethical leadership.',
                'There is no broadly accepted measurement instrument; dimensional structure remains contested.',
                'Antecedents and mechanisms are less developed than downstream outcomes, with heavy reliance on social learning and social exchange explanations.',
            ],
            'measurement_scales': [
                {
                    'name': 'Ethical Leadership Scale',
                    'source': 'Brown, Treviño, & Harrison (2005)',
                    'metadata': 'One dimension and 10 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Ethical Leadership Scale',
                    'source': 'Resick et al. (2006)',
                    'metadata': 'Four dimensions and 15 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Ethical Leadership Scale',
                    'source': 'De Hoogh & Den Hartog (2008)',
                    'metadata': 'Three dimensions and 17 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Ethical Leadership at Work Questionnaire',
                    'source': 'Kalshoven, Den Hartog, & De Hoogh (2011)',
                    'metadata': 'Seven dimensions and 38 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Leadership Virtues Questionnaire',
                    'source': 'Riggio et al. (2010)',
                    'metadata': 'Four dimensions and 19 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Chinese Ethical Leadership Questionnaire',
                    'source': '和孟慧等 (2014)',
                    'metadata': 'Three dimensions and 24 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
            ],
            'methods': [
                'Qualitative interviews used to identify ethical-leadership components.',
                'Survey scale development, validation, and cross-cultural comparison.',
                'Multi-method and multilevel studies of employee, team, and organizational outcomes.',
                'Mediation and moderation models involving psychological safety, meaning, ethical climate, LMX, and role modeling.',
            ],
            'cited_works': [
                'Enderle (1987)',
                'Treviño, Hartman, & Brown (2000)',
                'Treviño, Brown, & Hartman (2003)',
                'Brown, Treviño, & Harrison (2005)',
                'Brown & Treviño (2006)',
                'Eisenbeiss (2012)',
                'Walumbwa & Schaubroeck (2009)',
            ],
        },
        'evidence': [
            _entry(143, 160, 'definition',
                   'The chapter traces ethical leadership to Enderle and identifies ethical perception/creation, responsibility for decisions affecting others, and responsibility for organizational goals.'),
            _entry(144, 161, 'definition',
                   'Treviño\'s framework distinguishes the moral person from the moral manager; Brown et al.\'s social-learning definition emphasizes personal action, interpersonal relations, communication, reinforcement, and decisions.'),
            _entry(145, 162, 'construct',
                   'Interview and conceptual work lists people orientation, visible moral action, ethical standards and responsibility, broad moral awareness, and fair/open decision processes.'),
            _entry(145, 162, 'construct',
                   'The chapter contrasts ethical leadership with authentic, transformational, transactional, and spiritual leadership, locating moral management and role modeling at its core.'),
            _entry(146, 163, 'boundary_condition',
                   'Cross-cultural measurement is presented as a boundary issue, including the moral-person/moral-manager distinction, moral cognition, and ethical-climate building.'),
            _entry(147, 164, 'mechanism',
                   'Reported studies connect ethical leadership to work attitudes, performance, citizenship, and reduced deviance through social learning, social exchange, psychological safety, meaning, self-efficacy, LMX, and organizational identification.'),
            _entry(148, 165, 'boundary_condition',
                   'Antecedent and moderator discussions include leader traits, moral intensity, self-monitoring, power inhibition, employee age, empowerment, implicit theory, LMX, and role-modeling strength.'),
            _entry(148, 165, 'criticism',
                   'The evaluation identifies definitional ambiguity, disagreement over one versus multiple dimensions, underdeveloped antecedents, and incomplete mechanism explanations.'),
            _entry(149, 166, 'measurement',
                   'The chapter lists multiple ethical-leadership measures ranging from one to seven dimensions; the seed stores scale metadata only and does not copy items.'),
            _entry(150, 167, 'citation',
                   'The classic-works section includes Treviño, Brown, Harrison, Kanungo, Mendonca, Toor, Ofori, and related ethical-leadership sources.'),
        ],
    },
    'event-system-theory': {
        'coding': {
            'definition': (
                'Event System Theory combines variance-oriented and process-oriented views to '
                'explain how salient events experienced by entities produce dynamic effects through '
                'event strength, time, and space.'
            ),
            'constructs': [
                'event and focal entity',
                'event strength: novelty, disruption, and criticality',
                'event time: timing, duration, and change',
                'event space: origin, direction, dispersion, and distance',
                'event main effects and event-by-entity interactions',
                'routine, disruptive, active, and passive events',
                'event accumulation and multi-event systems',
            ],
            'mechanisms': [
                'stronger events attract more entity attention, resources, and investment and can change behavior or internal features',
                'event timing, duration, origin, dispersion, and distance moderate event-strength effects',
                'event attributes interact with entity characteristics and with one another',
                'multiple events can operate through distinct mediators and mutually reinforce or inhibit outcomes',
                'events can trigger subsequent events and organizational change',
            ],
            'boundary_conditions': [
                'The event must be a salient interaction among multiple entities and external to the focal entity.',
                'Effects depend on focal level, event type, time, space, strength, and the entity\'s developmental needs.',
                'The framework is intended for individual, team, organizational, and macro-level event settings.',
                'Routine-event accumulation and the distinction between active and passive events remain important scope conditions.',
            ],
            'criticisms': [
                'The chapter identifies the accumulation and integration of routine low-novelty, low-disruption, low-criticality events as an unresolved challenge.',
                'Quantifying the time, space, and strength attributes of complex events remains difficult.',
            ],
            'measurement_scales': [
                {
                    'name': 'Event Novelty',
                    'source': 'Morgeson (2005)',
                    'metadata': 'One dimension and four items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Event Disruption',
                    'source': 'Morgeson (2005)',
                    'metadata': 'One dimension and four items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Event Criticality',
                    'source': 'Morgeson & DeRue (2006)',
                    'metadata': 'One dimension and three items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
            ],
            'methods': [
                'Event-oriented variance models using event attributes as continuous predictors.',
                'Difference-in-differences event designs are cited as a related empirical design.',
                'Main-effect, moderation, interaction, and multi-event models.',
                'Qualitative event case studies that trace event attributes and process mechanisms.',
            ],
            'cited_works': [
                'Morgeson (2005)',
                'Morgeson & DeRue (2006)',
                'Morgeson, Mitchell, & Liu (2015)',
                'Zellmer-Bruhn (2003)',
                'Tilcsik & Marquis (2013)',
                'Liu, Fisher, & Chen (2018)',
            ],
        },
        'evidence': [
            _entry(152, 169, 'definition',
                   'The chapter positions Event System Theory as a response to variance-oriented research that underweights events experienced by individuals, teams, and organizations.'),
            _entry(153, 170, 'definition',
                   'Morgeson, Mitchell, and Liu are credited with the 2015 event-oriented formulation combining variance and process perspectives.'),
            _entry(153, 170, 'construct',
                   'An event is defined as a distinct, salient interaction among multiple entities with a location in time and space; it is external to the focal entity.'),
            _entry(154, 171, 'boundary_condition',
                   'The chapter separates events from persistent internal features such as personality, emotion, demographics, and organizational culture.'),
            _entry(154, 171, 'mechanism',
                   'Event strength is expected to attract attention, resources, and investment; timing, duration, origin, dispersion, and distance condition the resulting impact.'),
            _entry(155, 172, 'construct',
                   'The model organizes event strength around novelty, disruption, and criticality and links these dimensions to time and space attributes.'),
            _entry(156, 173, 'method',
                   'The chapter proposes main-effect, interaction, moderation, multi-event, and qualitative case-study designs for examining event processes.'),
            _entry(157, 174, 'criticism',
                   'The evaluation notes that routine events can accumulate and integrate into major organizational effects, but their evolution is not yet adequately captured.'),
            _entry(157, 174, 'measurement',
                   'The chapter lists Event Novelty, Event Disruption, and Event Criticality measures with four, four, and three items respectively; wording is not copied.'),
            _entry(158, 175, 'citation',
                   'The classic-works section includes the 2015 theory article, Morgeson and DeRue, Zellmer-Bruhn, Tilcsik and Marquis, and related event research.'),
        ],
    },
    'fairness-heuristic-theory': {
        'coding': {
            'definition': (
                'Fairness Heuristic Theory explains how people form an overall fairness judgment '
                'from limited fairness information and then use that judgment as a shortcut to '
                'interpret later information and guide organizational attitudes and behavior.'
            ),
            'constructs': [
                'fairness-judgment formation and use',
                'overall fairness judgment / fairness heuristic',
                'procedural, distributive, and interactional fairness information',
                'primacy effect',
                'substitutability effect',
                'fundamental social dilemma and relational security',
                'trust, cooperation, authority acceptance, identification, and citizenship behavior',
            ],
            'mechanisms': [
                'uncertainty or information ambiguity -> heuristic use of available fairness cues -> overall fairness impression',
                'early fairness information receives disproportionate weight through the primacy effect',
                'procedural, distributive, and interactional information can substitute for one another when one source is missing',
                'overall fairness judgment guides later interpretation, emotion, trust, cooperation, and self-versus-organization interests',
                'major or discrepant events can return people from the use stage to a new formation stage',
            ],
            'boundary_conditions': [
                'The theory is especially relevant under information scarcity, ambiguity, uncertainty, or insecurity.',
                'Group membership and the fundamental social dilemma make fairness informative about relational safety.',
                'Early relationship stages and first impressions are emphasized; organizationally relevant outcomes are more affected than purely individual outcomes.',
                'New mergers, restructurings, strategies, or other discrepant events can reset an established fairness heuristic.',
            ],
            'criticisms': [
                'The chapter leaves the weighting or resolution of contradictory fairness information unresolved.',
                'Interactional fairness, the amount of information required, and intermediate rather than binary judgments need more research.',
                'Some identity-shift and self-interest predictions remain insufficiently supported by empirical evidence.',
            ],
            'measurement_scales': [
                {
                    'name': 'Organizational Justice',
                    'source': 'Colquitt (2001)',
                    'metadata': 'Four dimensions and 20 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Organizational Justice',
                    'source': 'Niehoff & Moorman (1993)',
                    'metadata': 'Three dimensions and 20 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Justice Perceptions',
                    'source': 'Qin et al. (2015)',
                    'metadata': 'Three dimensions and 16 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Overall Justice',
                    'source': 'Ambrose & Schminke (2009)',
                    'metadata': 'One dimension and six items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Overall Justice',
                    'source': 'Jones & Martens (2010)',
                    'metadata': 'One dimension and three items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
            ],
            'methods': [
                'Experiments that manipulate the order or availability of procedural and distributive fairness information.',
                'Scenario and survey studies of overall fairness, trust, and justice judgments.',
                'Cross-cultural and workplace studies of fairness formation and use.',
                'Mediation and moderation models linking justice criteria to organizational attitudes and behavior.',
            ],
            'cited_works': [
                'Lind (1993, 2001)',
                'Lind, Kray, & Thompson (2001)',
                'Bos et al. (1997, 1998, 2001, 2004)',
                'Lind, Kulik, & Ambrose (1993)',
                'Kray & Thompson (2001)',
            ],
        },
        'evidence': [
            _entry(160, 177, 'definition',
                   'The chapter traces Fairness Heuristic Theory to Lind and frames it as an explanation of why and how people form fairness judgments.'),
            _entry(161, 178, 'construct',
                   'The core framework has a formation stage and a use stage, with primacy, substitutability, and related effects organizing the process.'),
            _entry(162, 179, 'mechanism',
                   'Under uncertainty or insecurity, people use available fairness information as a cognitive shortcut to form an overall impression rather than fully decomposing justice dimensions.'),
            _entry(162, 179, 'construct',
                   'The chapter links the overall fairness heuristic to trust, cooperation, authority and rule acceptance, self-esteem, citizenship, and self-versus-organization interests.'),
            _entry(163, 180, 'mechanism',
                   'Primacy gives early fairness information greater weight, while procedural, distributive, and interactional information can substitute when one source is unavailable.'),
            _entry(163, 180, 'boundary_condition',
                   'The heuristic is more persistent for organization-related attitudes and is revised when major or discrepant events such as restructuring occur.'),
            _entry(164, 181, 'criticism',
                   'The evaluation raises unresolved questions about contradictory information, weighting, intermediate judgments, interactional fairness, and the amount of information required.'),
            _entry(164, 181, 'measurement',
                   'The chapter lists organizational-justice, justice-perception, and overall-justice measures; this queue stores dimensions and item counts only.'),
            _entry(165, 182, 'citation',
                   'The classic-works section includes Bos, Lind, Vermunt, Wilke, Kray, Thompson, and organizational-justice foundations.'),
        ],
    },
    'feelings-as-information-theory': {
        'coding': {
            'definition': (
                'Feelings-as-Information Theory conceptualizes moods, emotions, metacognitive '
                'experiences, and bodily sensations as information that people may use in judgment '
                'and in selecting a processing style.'
            ),
            'constructs': [
                'mood and general valence information',
                'specific emotions and appraisal information',
                'metacognitive experiences such as ease or difficulty of retrieval',
                'bodily sensations and physiological state',
                'perceived information value and attribution',
                'judgment and evaluation',
                'top-down versus bottom-up / analytical processing style',
            ],
            'mechanisms': [
                'feeling -> information signal about the target or situation -> judgment',
                'misattribution to an irrelevant source weakens the feeling\'s influence on judgment',
                'positive feeling signals a benign situation and supports broad, top-down processing',
                'negative feeling signals a problematic situation and supports detailed, bottom-up processing',
                'ease or difficulty of recall supplies information about the self when its source is not discounted',
            ],
            'boundary_conditions': [
                'Influence depends on perceived relevance, information value, source attribution, and whether the feeling is changing or stable.',
                'The effect is stronger when the judgment is self-relevant and when expertise or other diagnostic inputs are less accessible.',
                'Processing capacity, motivation, task demands, comparison standards, and the judgment target condition the effect.',
                'Mood, discrete emotion, metacognitive experience, and bodily sensation carry different information and should not be collapsed without justification.',
            ],
            'criticisms': [
                'The chapter notes that the theory cannot explain all positive-versus-negative affect findings in creativity research.',
                'Workplace applications beyond affect and creativity remain relatively limited.',
                'The theory should be combined with employee characteristics and contextual factors rather than treated as a complete account of affective effects.',
            ],
            'measurement_scales': [
                {
                    'name': 'Positive and Negative Affect Schedule (PANAS)',
                    'source': 'Watson, Clark, & Tellegen (1988)',
                    'metadata': 'Two dimensions and 20 affect terms as listed in the chapter; item wording is not copied.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'PANAS-X',
                    'source': 'Watson & Clark (1999)',
                    'metadata': 'Eleven affect categories and 60 specific affects as listed in the chapter; item wording is not copied.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
            ],
            'methods': [
                'Mood induction through autobiographical recall and environmental cues such as room pleasantness or weather.',
                'Misattribution experiments that manipulate the perceived source of a feeling.',
                'Judgment and processing-style experiments involving life satisfaction, targets, recall ease, and creative tasks.',
                'The chapter also cites cross-country weather and stock-market evidence as an application example.',
            ],
            'cited_works': [
                'Schwarz & Clore (1983, 2003, 2007)',
                'Schwarz (1990, 1998, 2012)',
                'Clore, Schwarz, & Conway (1994)',
                'Schwarz et al. (1987, 1991)',
                'Watson, Clark, & Tellegen (1988)',
                'Hirshleifer & Shumway (2003)',
            ],
        },
        'evidence': [
            _entry(168, 185, 'definition',
                   'The chapter traces the theory to Schwarz and Clore and presents it as an account of how feelings and thinking interact in judgment.'),
            _entry(169, 186, 'definition',
                   'Moods, emotions, metacognitive experiences, and bodily sensations are treated as different kinds of subjective information used in later judgments.'),
            _entry(169, 186, 'method',
                   'The originating experiments combine mood induction with attribution manipulations and use life-satisfaction judgment as an outcome.'),
            _entry(170, 187, 'mechanism',
                   'The chapter distinguishes information carried by discrete emotion, diffuse mood, cognitive ease or difficulty, and bodily sensation, with target relevance determining value.'),
            _entry(171, 188, 'boundary_condition',
                   'Feeling effects depend on whether the feeling is discounted, self-relevant, changing, and diagnostic, as well as on available expertise, processing capacity, and motivation.'),
            _entry(172, 189, 'mechanism',
                   'Positive feelings are described as signals of a benign situation that support broad top-down processing, while negative feelings signal problems and support detailed bottom-up processing.'),
            _entry(173, 190, 'criticism',
                   'The evaluation emphasizes broad applicability but cautions that the theory cannot explain every affect-creativity pattern and has limited workplace coverage.'),
            _entry(173, 190, 'measurement',
                   'The chapter lists PANAS and PANAS-X with two/20 and 11/60 metadata respectively; the seed records no item wording.'),
            _entry(174, 191, 'citation',
                   'The classic-works section includes Schwarz, Clore, Conway, and the core mood-as-information and feelings-as-information sources.'),
        ],
    },
    'goal-orientation-theory': {
        'coding': {
            'definition': (
                'Goal Orientation Theory describes the cognitive and behavioral patterns that '
                'arise from pursuing achievement goals, especially learning/mastery, performance '
                'approach, and performance avoidance orientations.'
            ),
            'constructs': [
                'learning / mastery goal orientation',
                'performance-prove / performance-approach orientation',
                'performance-avoidance orientation',
                'task, ego, social, and work-avoidance orientations',
                'implicit theories of intelligence: incremental and entity beliefs',
                'individual and team goal orientation',
                'goal-oriented cognition, emotion, motivation, and behavior',
            ],
            'mechanisms': [
                'incremental ability beliefs -> learning orientation -> development, self-efficacy, intrinsic motivation, and creativity',
                'performance-avoidance orientation -> concern about exposing inadequacy -> anxiety and reduced self-efficacy',
                'goal orientation shapes interpretation of achievement events and subsequent cognitive, emotional, and behavioral patterns',
                'team goal orientation -> information elaboration/reflexivity -> team creativity, adaptability, and innovation',
                'task difficulty, team trust, and conflict can change the strength or direction of goal-orientation effects',
            ],
            'boundary_conditions': [
                'The chapter reports an unresolved state-versus-trait-versus-situation-specific conceptualization.',
                'Learning and performance orientations can coexist; they are not necessarily opposite ends of one continuum.',
                'Task difficulty, challenge, team composition, goal-orientation diversity, leadership trust, and team climate condition effects.',
                'The unit of analysis can be individual, team, or cross-level.',
            ],
            'criticisms': [
                'The chapter highlights conceptual ambiguity about whether goal orientation is a goal, trait, state, or emergent cognitive-behavioral pattern.',
                'Different definitions have produced inconsistent or contradictory findings, especially in organizational research.',
                'The theoretical basis linking implicit intelligence beliefs to goal orientation is described as insufficiently strong.',
            ],
            'measurement_scales': [
                {
                    'name': 'Achievement Goal Items',
                    'source': 'Elliot & Church (2004)',
                    'metadata': 'Three dimensions and 18 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Work Domain Goal Orientation Instrument',
                    'source': 'Vandewalle (1997)',
                    'metadata': 'Three dimensions and 16 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Goal Orientation Measures',
                    'source': 'Button, Mathieu, & Zajac (1996)',
                    'metadata': 'Two dimensions and 16 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Achievement Goal Orientations Scale',
                    'source': 'Midgley et al. (1998)',
                    'metadata': 'Three dimensions and 18 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Motivated Strategies for Learning Questionnaire',
                    'source': 'Pintrich et al. (1993)',
                    'metadata': 'Fifteen dimensions and 81 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Goal Orientation Items',
                    'source': 'Skaalvik (1997)',
                    'metadata': 'Four dimensions and 22 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
            ],
            'methods': [
                'Individual-level achievement motivation and organizational behavior studies.',
                'Experimental studies of task difficulty, goal orientation, and team outcomes.',
                'Survey, mediation, moderation, and multilevel studies of individual and team goal orientation.',
                'Scale development and validation across educational and work-domain contexts.',
            ],
            'cited_works': [
                'Dweck (1986)',
                'Dweck & Leggett (1988)',
                'Elliot & Harackiewicz (1996)',
                'Cury et al. (2006)',
                'DeShon & Gillespie (2005)',
                'Vandewalle (1997)',
                'Payne et al. (2007)',
            ],
        },
        'evidence': [
            _entry(176, 193, 'definition',
                   'The chapter traces goal orientation to Dweck\'s achievement-goal work and describes it as a major cognitive-motivational perspective in management and organizational research.'),
            _entry(177, 194, 'construct',
                   'Learning goals emphasize task mastery and capability development, whereas performance goals emphasize demonstrating ability or avoiding evidence of inadequacy.'),
            _entry(178, 195, 'construct',
                   'The chapter distinguishes performance approach and performance avoidance and also records task, ego/social, work-avoidance, and three-factor work-domain formulations.'),
            _entry(178, 195, 'mechanism',
                   'Incremental versus entity beliefs about intelligence are used to explain why some people pursue learning goals while others seek performance validation or avoid negative evaluation.'),
            _entry(179, 196, 'definition',
                   'DeShon and Gillespie are presented as treating goal orientation as a cognitive-behavioral pattern generated while pursuing a particular achievement goal in a specific context.'),
            _entry(180, 197, 'mechanism',
                   'Individual studies link learning orientation to intrinsic motivation, self-efficacy, cooperation, and creativity, while performance avoidance is linked to anxiety and weaker self-efficacy.'),
            _entry(181, 198, 'mechanism',
                   'Team-level studies connect shared goal orientation and goal-orientation diversity to information elaboration, reflexivity, team creativity, and innovation, with trust and composition as conditions.'),
            _entry(182, 199, 'criticism',
                   'The evaluation emphasizes disagreement over whether goal orientation is a goal, trait, state, or context-specific pattern and notes a weak or contested theoretical foundation.'),
            _entry(182, 199, 'measurement',
                   'The chapter begins a list of goal-orientation instruments; this queue stores dimensions, item counts, and sources only, without reproducing items.'),
            _entry(183, 200, 'measurement',
                   'The scale list includes work-domain, achievement-goal, personal-goal, learning-strategy, and goal-orientation measures; the classic section includes Dweck, Elliot, and DeShon.'),
        ],
    },
    'implicit-leadership-theory': {
        'coding': {
            'definition': (
                'Implicit Leadership Theory explains leadership perception through followers\' '
                'cognitive schemas and prototypes of leader attributes, while also considering '
                'leaders\' implicit theories about followers.'
            ),
            'constructs': [
                'leader prototype and leader antiprototype',
                'implicit leadership beliefs and cognitive schemas',
                'leader categorization and prototype matching',
                'implicit followership theories',
                'leader/follower attribution, evaluation, and expectations',
                'culture-specific and context-specific leadership attributes',
                'leader effectiveness and follower outcomes',
            ],
            'mechanisms': [
                'attention, selection, encoding, processing, and memory -> stored leader schema',
                'observed leader attributes/behavior compared with a prototype -> leader categorization and evaluation',
                'prototype match or mismatch shapes attribution, attitudes, behavior, and perceived effectiveness',
                'leaders categorize followers using implicit followership schemas, influencing exchange and follower outcomes',
                'communication and richer objective information can reduce overreliance on prototypes',
            ],
            'boundary_conditions': [
                'Culture and national context shape the content and factor structure of leader prototypes.',
                'Follower identity, social categories, work context, gender, and changing organizational conditions can alter prototype use.',
                'Leader and follower schemas may operate simultaneously and can be congruent or discrepant.',
                'The chapter emphasizes individual cognition but also points to group and organizational consequences.',
            ],
            'criticisms': [
                'The chapter says the research base is still insufficient relative to changes in work, gender roles, women managers, and economic conditions.',
                'How leaders\' and followers\' perceptions jointly affect goal achievement is not yet clearly explained.',
                'The transferability of existing prototypes to contemporary Chinese organizational contexts remains uncertain.',
            ],
            'measurement_scales': [
                {
                    'name': '59 Leader Attributes Scale',
                    'source': 'Lord, Foti, & Vader (1984)',
                    'metadata': 'Two dimensions and 59 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Implicit Leadership Theories Scale',
                    'source': 'Offermann et al. (1994)',
                    'metadata': 'Eight dimensions and 41 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Implicit Leadership Theories Factor Structure Scale',
                    'source': 'Epitropaki & Martin (2004)',
                    'metadata': 'Six dimensions and 21 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Chinese Implicit Leadership Scale',
                    'source': '凌文辁, 方俐洛, & 艾尔卡 (1991)',
                    'metadata': 'Four dimensions and 19 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Implicit Leadership Theory Measure',
                    'source': '卢会志 (2008)',
                    'metadata': 'Eight dimensions and 51 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
            ],
            'methods': [
                'Cognitive categorization and information-processing studies of leader perception.',
                'Survey scale development, factor-structure, generalizability, and stability studies.',
                'Cross-cultural comparison of leader attributes and applied organizational settings.',
                'Follower- and leader-side studies of prototype matching, attitudes, exchange, and performance.',
            ],
            'cited_works': [
                'Eden & Leviatan (1975)',
                'Lord, Foti, & Vader (1984)',
                'Lord & Maher (1991)',
                'Offermann et al. (1994)',
                'Den Hartog et al. (1999)',
                'Epitropaki & Martin (2004)',
                'Sy (2010)',
            ],
        },
        'evidence': [
            _entry(186, 203, 'definition',
                   'The chapter frames leadership influence as mediated by cognition and introduces implicit leadership as a shift from observable behavior toward internal schemas and processes.'),
            _entry(187, 204, 'definition',
                   'Eden and Leviatan are credited with applying implicit personality theory to leadership; implicit leadership is described as followers\' beliefs about leader attributes and capabilities.'),
            _entry(188, 205, 'mechanism',
                   'Information processing through attention, selection, encoding, processing, and memory produces leader prototypes and antiprototypes used to understand leader behavior.'),
            _entry(188, 205, 'construct',
                   'Prototype matching is presented as a basis for categorizing a person as an effective or ineffective leader and for evaluating leadership behavior.'),
            _entry(189, 206, 'mechanism',
                   'The chapter extends the information-processing perspective to implicit followership theories: leader perceptions of follower prototypes influence attitudes, exchange, and follower outcomes.'),
            _entry(190, 207, 'method',
                   'The evaluation identifies cognitive-psychology methods, prototype research, and applied organizational studies as contributions to leadership perception research.'),
            _entry(190, 207, 'criticism',
                   'The chapter notes insufficient research on contemporary work changes, gender and women managers, and how leader and follower perceptions jointly affect organizational goals.'),
            _entry(191, 208, 'measurement',
                   'The chapter lists five prototype and implicit-leadership measures with dimensions and item counts only; item wording is not copied.'),
            _entry(192, 209, 'boundary_condition',
                   'The management implications stress communication and richer objective information so that leader evaluations are not based only on pre-existing prototypes.'),
        ],
    },
    'interaction-ritual-chain-theory': {
        'coding': {
            'definition': (
                'Interaction Ritual Chain Theory treats recurring encounters as linked rituals in '
                'which shared attention, emotional synchrony, and symbolic boundaries generate '
                'emotional energy, solidarity, and cultural resources.'
            ),
            'constructs': [
                'interaction ritual and encounter',
                '共同关注 / shared focus of attention',
                'emotional synchrony and collective effervescence',
                'emotional energy',
                'cultural capital and shared symbols',
                'group solidarity, membership, and moral/emotional symbols',
                'power, status, center-periphery position, and ritual chains',
            ],
            'mechanisms': [
                'co-presence/shared attention -> emotional synchrony -> shared symbols and moral feelings',
                'successful ritual -> emotional energy, solidarity, and cultural capital -> participation in later rituals',
                'individuals seek rituals that maximize positive emotional energy relative to time and effort costs',
                'power and status differences distribute emotional energy unevenly between central and peripheral participants',
                'repeated rituals form chains that connect micro interaction to group and macro social structure',
            ],
            'boundary_conditions': [
                'Physical or symbolic co-presence, common focus, emotional entrainment, and shared boundaries are conditions for a successful ritual.',
                'Power, status, membership, center-periphery position, and access to cultural capital shape emotional-energy returns.',
                'Expressive and instrumental rituals may produce different social resources and practical outcomes.',
                'The focal context can be workplace, online community, religion, consumption, education, or governance.',
            ],
            'criticisms': [
                'The chapter says emotional energy is central but ambiguously defined and that negative emotional energy receives insufficient attention.',
                'Ritual, encounter, resource, and related concepts are described as broad or insufficiently specified.',
                'The theory may overgeneralize ritual while underplaying the independent cultural logic of ideas, symbols, and narratives.',
            ],
            'measurement_scales': [
                {
                    'name': 'Affect-based Trust Scale',
                    'source': 'Zhang, Liu, & Liu (2015)',
                    'metadata': 'Five items as listed in the chapter; no dimension count was provided.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Cognition-and-Affect-based Trust Scale',
                    'source': 'Ng & Chua (2006)',
                    'metadata': 'Two dimensions and 10 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Positive and Negative Emotional Energy',
                    'source': 'Boyns & Luery (2015)',
                    'metadata': 'Three dimensions and 16 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Empathy Scale',
                    'source': 'Tian & Robertson (2017)',
                    'metadata': 'Ten items as listed in the chapter; no dimension count was provided.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
            ],
            'methods': [
                'Micro-sociological interaction and encounter analysis.',
                'Qualitative case studies of brands, online fan communities, religion, tourism, and organizations.',
                'Survey and scale-based studies of emotional energy, trust, empathy, and group solidarity.',
                'Multi-level interpretation linking interaction rituals to group and macro social structure.',
            ],
            'cited_works': [
                'Collins (1987, 2004)',
                'Durkheim (1995)',
                'Castro-Santos (2008)',
                'Wellman, Corcoran, & Kate (2014)',
                'Cottingham (2012)',
                'Boyns & Luery (2015)',
            ],
        },
        'evidence': [
            _entry(193, 210, 'definition',
                   'The chapter introduces Collins\' interaction ritual chain formulation as a bridge between micro interaction, emotion, individual action, and social structure.'),
            _entry(194, 211, 'definition',
                   'An interaction ritual is described as an encounter in which participants share a focus of attention and sense one another\'s bodily rhythms and emotions.'),
            _entry(195, 212, 'mechanism',
                   'Shared attention and emotional synchrony generate equivalent symbols, moral feelings, cultural capital, and emotional energy; emotional energy is presented as the primary motivational resource.'),
            _entry(196, 213, 'boundary_condition',
                   'Power and status differences distribute emotional energy unevenly, with central or high-status participants gaining energy and peripheral or dominated participants losing it.'),
            _entry(197, 214, 'method',
                   'Cited applications include brand crisis, tourism, culture, communication, education, sport, governance, and organizational interaction case studies.'),
            _entry(198, 215, 'criticism',
                   'The evaluation praises the micro-to-macro bridge but criticizes ambiguous emotional energy, underdeveloped negative emotion, and broad concepts with limited methodological detail.'),
            _entry(198, 215, 'measurement',
                   'The chapter lists trust, emotional-energy, and empathy measures; metadata is stored without reproducing any scale wording.'),
            _entry(199, 216, 'citation',
                   'The classic-works section includes Collins, Durkheim-related foundations, Castro-Santos, and Wellman et al. on megachurch interaction rituals.'),
            _entry(200, 217, 'boundary_condition',
                   'The management implications emphasize shared leader-follower attention, common symbols, group solidarity, and the need to combine ritual analysis with cognition and other theories.'),
        ],
    },
    'job-demands-resources': {
        'coding': {
            'definition': (
                'The Job Demands–Resources model classifies work characteristics as demands or '
                'resources and explains employee well-being through health-impairment and motivation '
                'pathways, with resources also buffering demands and supporting coping.'
            ),
            'constructs': [
                'job demands: workload, role conflict, time pressure, insecurity, emotional and physical demands',
                'job resources: social support, autonomy, feedback, control, development, and career resources',
                'health-impairment / exhaustion pathway',
                'motivational / work-engagement pathway',
                'resource buffering and coping hypotheses',
                'burnout and work engagement',
                'personal resources and engaging leadership',
            ],
            'mechanisms': [
                'high demands plus insufficient resources -> energy depletion/burnout -> negative health and organizational outcomes',
                'abundant resources -> motivation and work engagement -> commitment, retention, and performance',
                'resources buffer the negative effect of high demands on exhaustion',
                'high demands can activate resource use and strengthen the resource-to-performance relationship in challenging settings',
                'personal resources and engaging leadership alter demands, resources, autonomy, competence, and relatedness',
            ],
            'boundary_conditions': [
                'The model is designed to be flexible across occupations, organizations, and specific job contexts.',
                'Resource buffering and coping effects depend on the level and type of demands and resources.',
                'Stable personal traits and developable personal resources may occupy different causal positions.',
                'The model operates at individual and social/team levels and can incorporate leadership and organizational resources.',
            ],
            'criticisms': [
                'The chapter reports weak or contested evidence for demand-resource interaction effects.',
                'The position and role of personal resources in the model remain unclear and may vary by resource type.',
                'The flexibility of the model creates measurement and boundary-definition challenges across occupations.',
            ],
            'measurement_scales': [
                {
                    'name': 'Questionnaire on the Experience and Evaluation of Work',
                    'source': 'Van Veldhoven et al. (2002)',
                    'metadata': '27 dimensions and 203 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Copenhagen Psychosocial Questionnaire',
                    'source': 'Kristensen et al. (2005)',
                    'metadata': '30 dimensions and 135 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Nordic Questionnaire for Psychosocial and Social Factors at Work',
                    'source': 'Elo et al. (2000)',
                    'metadata': '30 dimensions and 145 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Health and Safety Executive Management Standards Indicator Tool',
                    'source': 'Edwards & Webster (2012)',
                    'metadata': 'Seven dimensions and 35 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Energy Compass',
                    'source': 'Schaufeli (2015)',
                    'metadata': '58 dimensions and 133 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
            ],
            'methods': [
                'Longitudinal and multi-sample studies of work demands, resources, burnout, and engagement.',
                'Mediation tests of health-impairment and motivational pathways.',
                'Moderation tests of resource buffering and coping under high demands.',
                'Occupational psychosocial-risk surveys and context-specific online measurement.',
            ],
            'cited_works': [
                'Demerouti et al. (2001)',
                'Bakker & Demerouti (2007)',
                'Schaufeli & Bakker (2004)',
                'Xanthopoulou et al. (2007, 2009)',
                'Schaufeli & Taris (2013, 2014)',
                'Schaufeli (2015, 2017)',
            ],
        },
        'evidence': [
            _entry(201, 218, 'definition',
                   'The chapter traces JD-R to Demerouti et al. (2001), later extensions adding work engagement, personal resources, and engaging leadership.'),
            _entry(202, 219, 'construct',
                   'Job demands consume physical, psychological, social, or effort resources, whereas job resources help achieve goals, reduce costs, and support growth and development.'),
            _entry(202, 219, 'mechanism',
                   'The dual-pathway hypothesis distinguishes a health-impairment path from demands to burnout and negative outcomes and a motivational path from resources to engagement and positive outcomes.'),
            _entry(203, 220, 'mechanism',
                   'Resources are described as having intrinsic motivational potential; increasing resources can both reduce burnout and increase engagement, whereas reducing demands mainly affects exhaustion.'),
            _entry(203, 220, 'boundary_condition',
                   'The buffering hypothesis states that autonomy, feedback, social support, and high-quality leader relations can weaken the impact of demanding work on exhaustion.'),
            _entry(204, 221, 'mechanism',
                   'The coping hypothesis proposes that high demands can strengthen the conversion of resources into performance when employees actively mobilize resources in challenging conditions.'),
            _entry(205, 222, 'construct',
                   'The model has expanded to personal resources and engaging leadership, and is related to COR, job demand-control, and effort-reward imbalance models.'),
            _entry(206, 223, 'criticism',
                   'The evaluation questions the empirical strength of demand-resource interaction and the causal position of stable versus developable personal resources.'),
            _entry(206, 223, 'measurement',
                   'The chapter lists broad psychosocial-work and energy measures; the queue preserves dimensions, item counts, and source references only.'),
            _entry(207, 224, 'citation',
                   'The classic-works section includes Demerouti, Bakker, Schaufeli, Taris, and Xanthopoulou contributions to the model and its applications.'),
        ],
    },
    'leader-member-exchange': {
        'coding': {
            'definition': (
                'Leader–Member Exchange theory treats leadership as differentiated, reciprocal '
                'social exchange relationships between a leader and individual members, developing '
                'from role expectations and socialization into higher- or lower-quality exchanges.'
            ),
            'constructs': [
                'leader-member exchange quality',
                'vertical dyadic linkage and role formation',
                'in-group and out-group membership',
                'economic and social exchange',
                'trust, loyalty, contribution, affect, and professional respect',
                'relative LMX, LMX differentiation, group/team LMX',
                'employee performance, satisfaction, commitment, citizenship, and withdrawal',
            ],
            'mechanisms': [
                'role expectations -> mutual evaluation/trust/loyalty -> socialization -> stable exchange relationship',
                'high-quality exchange -> support, information, resources, obligation, and reciprocity -> positive employee outcomes',
                'low-quality exchange -> restricted interaction/resources and economic exchange -> lower commitment and defensive behavior',
                'differentiated exchanges create in-group/out-group patterns and can spill over to team conflict, envy, and fairness perceptions',
                'relative and group-level LMX compare individual relationships and shape team-level consequences',
            ],
            'boundary_conditions': [
                'Leader time and organizational resources limit the possibility of identical relationships with every member.',
                'Role expectations, performance, ability/contribution, socialization, and relational reciprocity shape exchange development.',
                'Cultural context, relational norms, team LMX mean, and LMX differentiation condition individual effects.',
                'The unit of analysis may be dyadic, individual, group, team, or cross-level.',
            ],
            'criticisms': [
                'The chapter notes limited attention to effects on leaders rather than only employees.',
                'No universally accepted measure captures the dynamic formation process, partly because the construct remains conceptually disputed.',
                'Findings vary across countries and the theory remains underdeveloped in Chinese localization and cross-level research.',
                'Differentiated in-group/out-group relations can create inequality, conflict, envy, exclusion, and perceived favoritism.',
            ],
            'measurement_scales': [
                {
                    'name': 'LMX-MDM Scale',
                    'source': 'Liden & Maslyn (1998)',
                    'metadata': 'Four dimensions and 12 items: affect, loyalty, contribution, and professional respect as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'LMX-7 Scale',
                    'source': 'Gerstner & Day (1997)',
                    'metadata': 'Seven items as listed in the chapter; no dimension count was provided.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'LMX-6 Scale',
                    'source': 'Schriesheim et al. (1992)',
                    'metadata': 'Three dimensions and six items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Leader-Member Social Exchange Scale',
                    'source': 'Bernerth et al. (2007)',
                    'metadata': 'Eight items as listed in the chapter; no dimension count was provided.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'LMX-5 Scale',
                    'source': 'Basu & Green (1997)',
                    'metadata': 'Five items as listed in the chapter; no dimension count was provided.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
            ],
            'methods': [
                'Dyadic and longitudinal studies of exchange development and socialization.',
                'Survey scale development, construct validation, and meta-analysis.',
                'Mediation and multilevel studies of individual, team, and organizational outcomes.',
                'Relative-LMX and LMX-differentiation comparisons within teams.',
            ],
            'cited_works': [
                'Dansereau, Graen, & Haga (1975)',
                'Graen et al. (1982)',
                'Dienesch & Liden (1986)',
                'Graen & Uhl-Bien (1995)',
                'Gerstner & Day (1997)',
                'Liden & Maslyn (1998)',
                'Dulebohn et al. (2012)',
            ],
        },
        'evidence': [
            _entry(209, 226, 'definition',
                   'The chapter traces LMX to Graen and Dansereau\'s socialization work and defines it as a relationship-based social exchange between leaders and members.'),
            _entry(210, 227, 'mechanism',
                   'LMX formation is described as a reciprocal process of role expectations, mutual evaluation, trust, loyalty, socialization, and movement from economic to social exchange.'),
            _entry(211, 228, 'construct',
                   'High-exchange in-group members receive more care, support, time, and resources, while out-group relationships are more limited to formal duties.'),
            _entry(211, 228, 'construct',
                   'The chapter traces the shift from a one-dimensional exchange-quality view to multidimensional affect, loyalty, contribution, professional respect, and related formulations.'),
            _entry(212, 229, 'mechanism',
                   'High LMX is linked to support, information, motivation, reciprocity, performance, citizenship, satisfaction, and commitment, while low or unequal LMX can produce withdrawal and conflict.'),
            _entry(213, 230, 'boundary_condition',
                   'Relative LMX, LMX differentiation, group/team LMX, and comparisons with the team mean are introduced as group-level conditions and extensions.'),
            _entry(214, 231, 'criticism',
                   'The evaluation notes limited leader-side and cross-level research, lack of a universally accepted dynamic measure, inconsistent cross-national findings, and incomplete Chinese localization.'),
            _entry(214, 231, 'measurement',
                   'The chapter lists LMX-MDM, LMX-7, LMX-6, LMSX, and LMX-5 measures with dimensions and item counts only; item wording is not copied.'),
            _entry(215, 232, 'citation',
                   'The classic-works section includes Dienesch and Liden, Graen and Uhl-Bien, Gerstner and Day, Liden and Maslyn, and related social-exchange studies.'),
            _entry(216, 233, 'boundary_condition',
                   'The management discussion warns that in-group/out-group differentiation can become self-fulfilling and unequal, so selection and assignment should use clear contribution-based criteria.'),
        ],
    },
    'loose-coupling-theory': {
        'coding': {
            'definition': (
                'Loose coupling theory describes organizational elements as mutually responsive '
                'but retaining identity, autonomy, and physical or logical separation; it explains '
                'how formal structures can coexist with locally variable activity and practice.'
            ),
            'constructs': [
                'coupling relationship and coupling strength',
                'tight coupling, loose coupling, and non-coupling',
                'organizational elements, mechanisms, structural dimensions, and domains',
                'formal structure, legitimacy, and local practice',
                'modularity, autonomy, buffering, adaptation, and organizational effectiveness',
                'organizational process / organizing',
                'loose-coupled innovation networks and network-node independence',
            ],
            'mechanisms': [
                'low or irregular interaction frequency makes loose coupling more likely',
                'indirect relationships through third parties reduce immediate responsiveness',
                'causal uncertainty and fragmented external/internal environments weaken direct coupling',
                'delayed effects prevent one element from responding at the same time as another',
                'shared beliefs, norms, and institutional expectations connect elements while allowing local variation',
                'loose coupling can maintain, buffer, adapt, satisfy, and support effectiveness, while also enabling modular innovation',
            ],
            'boundary_conditions': [
                'The chapter emphasizes education and administration but extends applications to for-profit organizations, alliances, industry, and innovation networks.',
                'Coupling is state-like and can shift between tight and loose across stages or situations.',
                'Network effects differ for modular innovation and architectural innovation, and tight versus loose coupling has different information and trust consequences.',
                'The theory concerns relationships among elements and organizing processes rather than a permanently fixed organizational structure.',
            ],
            'criticisms': [
                'The chapter reports that coupling is conceptually vague and lacks a generally accepted precise definition.',
                'Researchers disagree about whether loose coupling is a desirable management solution or an organizational deficiency to be corrected.',
                'The state-like variability of coupling makes identification and management difficult.',
                'The chapter calls for clearer structural components, concrete definitions, and tools for identifying coupling degree.',
            ],
            'measurement_scales': [
                {
                    'name': 'Seven Coupling Dimensions in the School Organization Dimension Assessment (SODA) Instrument',
                    'source': 'Wilson, Firestone, & Herriott (1983)',
                    'metadata': 'Seven items/dimensions are listed in the chapter; examples include horizontal communication, vertical communication, centralization of classroom instruction, centralization of curriculum/resources, rule enforcement, and goals.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'National data loose-coupling test',
                    'source': 'Gao (2016)',
                    'metadata': 'Teacher composite indicator with five items and school-district composite indicator with three items, analyzed with two-level hierarchical linear models using SASS surveys.',
                    'status': 'chapter-reported operationalization; primary-source verification required',
                },
                {
                    'name': 'Asset-management loose-coupling mixed-method measure',
                    'source': 'Marriott, Mellett, & Macniven (2011)',
                    'metadata': 'Four questions covering capital-asset records, accounting consequences, register-update frequency, and asset-verification frequency.',
                    'status': 'chapter-reported operationalization; primary-source verification required',
                },
            ],
            'methods': [
                'Organizational case and conceptual analysis of coupling among elements, departments, organizations, and environments.',
                'Two-level hierarchical linear models using teacher, school, and district survey data.',
                'Mixed methodology combining semi-structured analysis/interviews with questionnaire evidence in asset-management systems.',
                'Network and comparative analysis of tight versus loose alliance structures and innovation outcomes.',
            ],
            'cited_works': [
                'Weick (1976)',
                'Meyer & Rowan (1977)',
                'Orton & Weick (1990)',
                'Beekun & Glick (2001)',
                'Hofman, Halman, & Song (2017)',
                'Marriott, Mellett, & Macniven (2011)',
            ],
        },
        'evidence': [
            _entry(218, 235, 'definition',
                   'The chapter traces loose coupling from Glassman and Weick and describes organizational elements as responsive while retaining identity and physical or logical separation.'),
            _entry(219, 236, 'construct',
                   'Loose coupling is contrasted with tight and non-coupling and is linked to the coexistence of standardized, legitimate formal structures with context-dependent local activity.'),
            _entry(219, 236, 'mechanism',
                   'The chapter identifies low interaction frequency, indirect relationships, causal uncertainty, and delayed effects as conditions that can produce loose coupling.'),
            _entry(220, 237, 'construct',
                   'The five research streams distinguish causes, classifications, direct effects, deficiencies, and performance consequences; listed consequences include maintenance, buffering, adaptation, satisfaction, and effectiveness.'),
            _entry(220, 237, 'boundary_condition',
                   'Applications extend from education and administration to firms, alliances, industry analysis, and innovation networks; loose coupling is linked positively to modular innovation but negatively to architectural innovation in a cited study.'),
            _entry(221, 238, 'mechanism',
                   'The tight-versus-loose network discussion contrasts trust and tacit-knowledge access with the fresh or heterogeneous information and knowledge that looser connections can transmit.'),
            _entry(222, 239, 'criticism',
                   'The evaluation reports that coupling is vague, lacks a generally accepted definition, and can change from tight to loose across stages, making it a variable organizational state.'),
            _entry(222, 239, 'criticism',
                   'The chapter distinguishes coupling elements, mechanisms, structural dimensions, and domains and calls for clearer definitions and practical tools for identifying degree of coupling.'),
            _entry(223, 240, 'measurement',
                   'The key-measures section lists the seven-item SODA dimensions and a national-data test using five-item teacher and three-item district composite indicators with two-level hierarchical models.'),
            _entry(223, 240, 'method',
                   'A mixed-method application combines semi-structured qualitative analysis/interviews with a four-question questionnaire for asset-management systems.'),
            _entry(224, 241, 'citation',
                   'The classic-works section includes Weick, Orton and Weick, Beekun and Glick, Glassman, and later tight/loose alliance and innovation applications.'),
        ],
    },
    'middle-status-conformity-theory': {
        'coding': {
            'definition': (
                'Middle-status conformity theory proposes an inverted-U relationship between status '
                'position and conformity: middle-status actors conform most because they face salient '
                'status-loss concerns, whereas high-status actors have security and low-status actors '
                'have less to lose or are excluded from the audience.'
            ),
            'constructs': [
                'status position: high, middle, and low',
                'conformity and nonconforming/deviant behavior',
                'status insecurity, identity pride, and perceived status stability',
                'group norms, standards, and audience evaluation',
                'candidate–audience interface',
                'competitive conditions, status mobility, and market-entry barriers',
                'audience ranking and candidate differentiation',
            ],
            'mechanisms': [
                'middle-status actors fear losing an existing but not fully secure position and therefore conform more strongly to group behavior',
                'high-status actors have confidence and protection that permit deviation, while low-status actors have little status to lose or are less visible to the audience',
                'candidate competition first produces conformity to audience standards and later produces differentiation among accepted candidates',
                'audience comparison, ranking, and status categorization shape which candidate conditions are accepted or rejected',
                'nonconformity can reflect both punishment avoidance and rewards for displaying valued industry characteristics',
            ],
            'boundary_conditions': [
                'The theory depends on how high, middle, and low status are defined and on the boundaries between these categories.',
                'Audience and candidate heterogeneity, market-entry barriers, prior network position, and the salience of status threat condition the relationship.',
                'Industry norms are not necessarily static; changing internal and external conditions can alter conformity expectations over time.',
                'Applications span group experiments, innovation diffusion, professional markets, financial analysts, and organizational/industry settings.',
            ],
            'criticisms': [
                'The chapter criticizes high/middle/low status categories as potentially arbitrary and requires researchers to justify boundaries.',
                'Existing models often assume homogeneous audiences and homogeneous candidates, limiting realism and generalizability.',
                'Treating group norms as static overlooks dynamic changes in internal and external conditions.',
                'Innovation-diffusion applications have produced inconsistent conclusions across fields, so the inverted-U pattern needs contextual specification.',
            ],
            'methods': [
                'Laboratory conformity experiments manipulating perceived group status and acceptance conditions.',
                'Candidate–audience interface scenarios and market-based comparative analysis of status and conformity.',
                'Industry-specific operationalization of status and conformity, including a cited study of symphony performance organizations.',
            ],
            'cited_works': [
                'Kelley & Shapiro (1954)',
                'Dittes & Kelley (1956)',
                'Hollander (1958, 1961)',
                'Phillips & Zuckerman (2001)',
                'Podolny (1993)',
                'Durand & Kremp (2015)',
            ],
        },
        'evidence': [
            _entry(225, 242, 'definition',
                   'The chapter introduces middle-status conformity as the phenomenon that the least influential and most influential group members conform less than middle-status members.'),
            _entry(226, 243, 'method',
                   'The Kelley and Shapiro / Dittes and Kelley experiments manipulated perceived group acceptance and status and used a decision task to observe conformity to a group decision.'),
            _entry(226, 243, 'mechanism',
                   'The chapter summarizes an inverted-U relationship between status position and conformity and links middle-status conformity to concern about losing an existing position.'),
            _entry(227, 244, 'mechanism',
                   'High-status actors are described as having security and resources for deviation, low-status actors as having little to lose or limited audience visibility, and middle-status actors as most exposed to status threat.'),
            _entry(228, 245, 'construct',
                   'The candidate–audience interface treats candidates as offering conditions and audiences as selecting among them; candidate identity and status are shaped through competition and audience preference.'),
            _entry(229, 246, 'mechanism',
                   'The interface model separates an initial comparison/qualification phase that encourages conformity from a later selection phase that rewards differentiation among accepted candidates.'),
            _entry(229, 246, 'boundary_condition',
                   'Prior position, market-entry barriers, existing networks, audience ranking, and the permeability of the middle-status position condition how deviations are interpreted.'),
            _entry(230, 247, 'mechanism',
                   'Durand and Kremp are cited as extending the model from punishment for deviation to rewards for conforming to salient industry characteristics and for being similar to peers.'),
            _entry(230, 247, 'criticism',
                   'The evaluation requires justification of status-category boundaries and calls for heterogeneous audiences and candidates rather than homogeneous assumptions.'),
            _entry(231, 248, 'measurement',
                   'Because the theory is an abstraction of a social phenomenon, the chapter reports context-specific operationalization of status and conformity rather than a universal scale; Durand and Kremp are given as an example.'),
            _entry(231, 248, 'boundary_condition',
                   'The chapter identifies dynamic group norms and changing internal or external conditions as important extensions beyond static conformity expectations.'),
        ],
    },
    'minority-influence-theory': {
        'coding': {
            'definition': (
                'Minority influence theory explains how a numerically smaller group holding a conflicting '
                'position can influence a majority, especially when the minority is behaviorally consistent '
                'and stimulates validation, divergent thinking, or private conversion.'
            ),
            'constructs': [
                'minority and majority positions',
                'behavioral consistency and flexible consistency around core principles',
                'conflict, confidence, and competence',
                'comparison process and validation process',
                'public compliance, private conversion, and latent influence',
                'convergent versus divergent thinking',
                'minority dissent, team innovation, and decision quality',
            ],
            'mechanisms': [
                'consistent minority positions create conflict and encourage majority members to validate both minority and majority views',
                'validation and deeper information search can produce private conversion even without public agreement',
                'majority influence tends to elicit public compliance and convergent thinking, whereas minority influence can elicit divergent thinking and broader search',
                'unanimity rules require minority views to be considered and increase discussion, factual reasoning, confidence, and perceived fairness',
                'minority dissent can increase team innovation, helping norms, monitoring, and mutual assistance when the team engages with the dissent',
            ],
            'boundary_conditions': [
                'Consistency must signal confidence and competence but need not be mechanical repetition; flexible expression around core principles can matter.',
                'Minority size has a double-edged effect: it can increase perceived competence and direct influence while reducing perceived confidence and indirect/private influence.',
                'Norms emphasizing conformity/objectivity can suppress minority influence, whereas innovation norms can strengthen it.',
                'Epistemic motivation, prosocial motivation, decision rules, future interaction expectations, team learning orientation, and face-to-face versus virtual context condition effects.',
            ],
            'criticisms': [
                'One-shot laboratory groups may not represent complex, changing real teams.',
                'The chapter reports disagreement about whether consistency means repeating a position or elaborating its underlying logic.',
                'Core concepts and labels such as validation and divergent thinking can overlap or remain insufficiently differentiated.',
            ],
            'measurement_scales': [
                {
                    'name': 'Minority Dissent Scale',
                    'source': 'De Dreu & West (2001)',
                    'metadata': 'One dimension and four items as listed in the chapter; item wording is not copied.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
            ],
            'methods': [
                'Color-perception laboratory experiment manipulating minority consistency and majority responses.',
                'Jury and decision-rule experiments comparing unanimity with two-thirds-majority rules.',
                'Team-level experiments and multilevel studies of minority opinion expression, participation, learning orientation, and innovation.',
                'Meta-analysis and comparative studies of minority size, direct/public influence, and indirect/private influence.',
                'Face-to-face versus computer-mediated group discussion and newcomer-minority applications.',
            ],
            'cited_works': [
                'Moscovici, Lage, & Naffrechoux (1969)',
                'Moscovici (1980)',
                'Nemeth (1977, 1986)',
                'Wood et al. (1994)',
                'De Dreu & West (2001)',
                'De Dreu et al. (2008)',
                'Grant & Patil (2012)',
            ],
        },
        'evidence': [
            _entry(234, 251, 'definition',
                   'The chapter defines the minority as numerically smaller and holding a conflicting position and emphasizes behavioral consistency as a condition for influence.'),
            _entry(235, 252, 'method',
                   'Moscovici and colleagues’ color-perception experiment used two consistent minority confederates among six participants; the chapter reports a nonzero majority shift under consistent minority responding.'),
            _entry(235, 252, 'mechanism',
                   'The chapter distinguishes mechanical repetition from flexible consistency around core principles that communicates minority confidence and competence.'),
            _entry(236, 253, 'mechanism',
                   'Conversion theory contrasts majority comparison and public compliance with minority-triggered validation, deeper thinking, and private conversion.'),
            _entry(236, 253, 'construct',
                   'Nemeth’s extension shifts attention from whether the majority adopts the minority position to divergent thinking, broader information search, and decision-process quality.'),
            _entry(237, 254, 'method',
                   'A jury experiment is summarized as showing that unanimity rules increase discussion, diverse opinions, factual reliance, confidence, and perceived fairness even when the final decision does not change.'),
            _entry(237, 254, 'boundary_condition',
                   'Organizational applications include team innovation, helping norms, newcomers, virtual teams, and learning orientation; attention from the majority and expected future interaction affect influence.'),
            _entry(238, 255, 'boundary_condition',
                   'Minority size, situational norms, epistemic motivation, and prosocial motivation are identified as moderators; more members can increase direct influence while reducing indirect/private influence.'),
            _entry(239, 256, 'criticism',
                   'The evaluation questions transfer from one-shot laboratory groups to real teams and notes ambiguity in the definition of consistency and overlap among validation and divergent-thinking concepts.'),
            _entry(240, 257, 'measurement',
                   'The key-measures section lists several experimental paradigms and a one-dimensional, four-item Minority Dissent Scale; item wording is intentionally not copied.'),
            _entry(241, 258, 'citation',
                   'The classic-works section includes Moscovici, Nemeth, Wood, De Dreu and West, De Dreu et al., and organizational applications of minority dissent.'),
        ],
    },
    'moral-licensing-theory': {
        'coding': {
            'definition': (
                'Moral licensing theory explains how prior moral behavior or a moral self-view can give '
                'people psychological permission to engage in later ambiguous or immoral behavior, producing '
                'a “good then bad” pattern through moral credentials or accumulated moral credits.'
            ),
            'constructs': [
                'moral licensing and moral cleansing',
                'moral self-concept and moral self-perception',
                'moral credentials',
                'moral credits and moral-balance accounting',
                'prior moral behavior and subsequent immoral behavior',
                'organizational citizenship, counterproductive work behavior, abuse, and stakeholder irresponsibility',
                'external motivation, relationship identification, moral identity symbolization, and principled orientation',
            ],
            'mechanisms': [
                'prior good behavior activates a moral self-concept that can license later behavior',
                'moral credentials make an ambiguous later act easier to interpret as consistent with morality',
                'moral credits accumulate like a balance that can be spent to offset a knowingly immoral act',
                'cross-domain prior and later acts, concrete recent good acts, and private settings strengthen licensing in the cited work',
                'organizational citizenship, innovation, elite culture, and organizational reputation can create a context for employee or manager licensing',
            ],
            'boundary_conditions': [
                'Licensing is weaker when prior and later behavior occur in the same domain because reputation is more exposed.',
                'Concrete and temporally close prior moral behavior is more licensing-prone than abstract and distant behavior.',
                'Public settings can weaken licensing relative to private settings.',
                'External motivation can strengthen the path from organizational citizenship to licensing and deviance, while relationship identification, moral-identity symbolization, and principled orientation can constrain it.',
                'The chapter emphasizes discrimination, prosocial behavior, consumer behavior, and organizational management contexts.',
            ],
            'criticisms': [
                'A meta-analysis and replication evidence summarized in the chapter question the size and robustness of the moral-licensing effect.',
                'Studies often borrow measures from discrimination, moral identity, self-concept, or related constructs rather than using a settled licensing measure.',
                'Theory-derived scales are relatively recent and have limited broad validation, while subjective self-reports can overestimate moral standing.',
                'Research has focused more on negative outcomes than on possible anxiety-reducing or relationship-stabilizing effects.',
            ],
            'measurement_scales': [
                {
                    'name': 'Moral Credentials Measure',
                    'source': 'Aquino & Reed (2002)',
                    'metadata': 'Five items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Self-assessment Statements',
                    'source': 'Khan & Dhar (2006)',
                    'metadata': 'Four items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Moral Self-concept Measure',
                    'source': 'Stake (1994)',
                    'metadata': 'Six items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Moral Credits Measure',
                    'source': 'Lin, Ma, & Johnson (2016)',
                    'metadata': 'Five items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
            ],
            'methods': [
                'Laboratory and vignette experiments manipulating prior moral behavior, moral statements, or anticipated good behavior.',
                'Behavioral and self-report measures of discrimination, prosocial behavior, consumer choice, and later deviance.',
                'Organizational surveys and theory-based tests involving citizenship, counterproductive work behavior, ethical leadership, and tax/stakeholder outcomes.',
                'Meta-analysis and replication studies evaluating effect size and robustness.',
            ],
            'cited_works': [
                'Monin & Miller (2001)',
                'Merritt, Effron, & Monin (2010)',
                'Miller & Effron (2010)',
                'Effron et al. (2009)',
                'Khan & Dhar (2006)',
                'Klotz & Bolino (2013)',
                'Lin, Ma, & Johnson (2016)',
                'Blanken et al. (2015)',
            ],
        },
        'evidence': [
            _entry(242, 259, 'definition',
                   'The chapter introduces moral licensing as an explanation for a good-then-bad pattern and traces the concept to Monin and Miller’s work on moral credentials.'),
            _entry(243, 260, 'definition',
                   'Moral-balance theory is used to distinguish moral cleansing after prior bad behavior from licensing after prior good behavior; the chapter frames both as changes in perceived moral standing.'),
            _entry(244, 261, 'mechanism',
                   'Moral credentials make ambiguous later behavior appear morally consistent, whereas moral credits accumulate and offset a knowingly immoral act.'),
            _entry(244, 261, 'mechanism',
                   'The chapter identifies moral self-concept as a mediator linking prior moral behavior to later behavior through credentials and credits.'),
            _entry(245, 262, 'boundary_condition',
                   'Licensing is described as stronger across different domains, after concrete and recent good acts, and in relatively private settings; same-domain, abstract, distant, or public conditions weaken it.'),
            _entry(245, 262, 'boundary_condition',
                   'Applications span discrimination, prosocial behavior, consumer choice, and organizational settings in which citizenship, innovation, elite culture, or organizational reputation can precede licensing.'),
            _entry(246, 263, 'construct',
                   'Organizational outcomes discussed include employee counterproductive/deviant behavior, abusive supervision, corporate tax avoidance, and neglect of stakeholder responsibility.'),
            _entry(246, 263, 'boundary_condition',
                   'External motivation, relationship identification, moral-identity symbolization, and principled orientation are described as moderators of licensing and later misconduct.'),
            _entry(246, 263, 'criticism',
                   'The evaluation summarizes small or disputed effects, replication concerns, reliance on borrowed constructs, limited scale validation, and possible under-study of positive consequences.'),
            _entry(247, 264, 'measurement',
                   'The key-measures section lists five-item moral credentials, four self-assessment statements, six-item moral self-concept, and five-item moral credits records; item wording is not copied.'),
            _entry(248, 265, 'citation',
                   'The classic-works section includes Monin and Miller, Merritt et al., Miller and Effron, Effron and Monin, Klotz and Bolino, and the meta-analytic review by Blanken et al.'),
            _entry(249, 266, 'boundary_condition',
                   'The management discussion emphasizes monitoring positive-to-negative behavior shifts, self-control, ethical climate, and role-modeling while avoiding claims that the chapter’s recommendations are causal evidence.'),
        ],
    },
    'need-to-belong-theory': {
        'coding': {
            'definition': (
                'Need-to-belong theory treats the desire to form and maintain a minimum number of '
                'lasting, positive, and meaningful social bonds as a fundamental and widely shared human '
                'motivation that shapes emotion, cognition, and group behavior.'
            ),
            'constructs': [
                'need to belong / belongingness motivation',
                'frequent, positive, stable, and meaningful social bonds',
                'belongingness satisfaction and thwarted/deprived belongingness',
                'acceptance, rejection, social exclusion, and interpersonal connection',
                'loneliness, social cues, affect, cognition, self-esteem, and social functioning',
                'team/organizational belonging, organizational embeddedness, fairness, prosocial behavior, and work satisfaction',
                'belongingness versus attachment, power, achievement, and need for distinctiveness',
            ],
            'mechanisms': [
                'social connection and signals of acceptance satisfy the belongingness motive and support affiliation and learning',
                'thwarted belongingness or exclusion can produce defensive/aggressive behavior, lower prosocial behavior, negative affect, distrust, and cognitive changes',
                'belongingness can influence downstream work outcomes through team identification, organizational embeddedness, fairness perceptions, and social support',
                'loneliness, hostile cognition, emotion, team size, leader empathy, and social resources are proposed mediating or moderating processes',
                'inclusive leadership can support belonging while preserving member independence through support, fairness, and shared decision making',
            ],
            'boundary_conditions': [
                'Unlike attachment theory, belongingness is presented as a common human motive rather than primarily an individual-difference or dependency pattern, and relationships are substitutable.',
                'Effects vary with social exclusion/acceptance context, team size, leader empathy, social resources, fairness, and organizational setting.',
                'The chapter notes work-related applications but says empirical evidence has been concentrated in students or clinical/experimental contexts.',
                'Managers must balance belonging with distinctiveness; excessive conformity pressure can turn belonging into constraint and suppress voice or creativity.',
            ],
            'criticisms': [
                'Findings on the effects of belongingness deprivation on affect and cognition are inconsistent across experiments.',
                'The mediating role of emotion is disputed, with emotional numbing and hostile cognition offering alternative explanations.',
                'Evidence has been concentrated in student and clinical samples, limiting direct generalization to workers and organizations.',
                'Because belongingness is a broad foundational motive, the chapter calls for more systematic models and theoretically balanced experimental manipulations.',
            ],
            'measurement_scales': [
                {
                    'name': 'Sense of Belonging Instrument–Psychological (SOBI-P)',
                    'source': 'Hagerty & Patusky (1995)',
                    'metadata': '18 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Need to Belong Scale (NTBS)',
                    'source': 'Schreindorfer, Leary, & Keith (1996)',
                    'metadata': '10 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Belongingness subscale of the Interpersonal Needs Questionnaire (INQ)',
                    'source': 'Van Orden et al. (2012)',
                    'metadata': 'Nine items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'General Belongingness Scale (GBS)',
                    'source': 'Malone, Pillow, & Osman (2015)',
                    'metadata': '12 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
            ],
            'methods': [
                'Social-exclusion, rejection, acceptance, and belongingness-deprivation experiments.',
                'Surveys of belongingness, relationship satisfaction, loneliness, life satisfaction, and social cues.',
                'Student, clinical, and educational studies of relationships, learning, and social development.',
                'Workplace and team studies of inclusive leadership, organizational embeddedness, fairness, prosocial behavior, performance, and satisfaction.',
            ],
            'cited_works': [
                'Baumeister & Leary (1995)',
                'Baumeister (2012)',
                'Baumeister et al. (2007)',
                'Mellor et al. (2008)',
                'Pickett, Gardner, & Knowles (2004)',
                'Twenge et al. (2007)',
                'Randel et al. (2018)',
            ],
        },
        'evidence': [
            _entry(250, 267, 'definition',
                   'The chapter presents Baumeister and Leary’s 1995 formulation of need to belong as a fundamental motivation and traces its later growth across psychology, sociology, and management.'),
            _entry(251, 268, 'definition',
                   'The core proposition is framed around maintaining a minimum number of frequent, positive, stable, and meaningful social connections and the universality of this motive.'),
            _entry(252, 269, 'boundary_condition',
                   'The chapter distinguishes belongingness from attachment, affiliation, intimacy, power, and achievement: belongingness is common across social behavior and relationships are substitutable rather than tied to one attachment figure.'),
            _entry(252, 269, 'mechanism',
                   'Positive teacher–student relationships and inclusive leadership communicate acceptance, recognition, fairness, support, and shared decision making that can satisfy belongingness.'),
            _entry(252, 269, 'construct',
                   'Work-related applications link belongingness with team cooperation, learning, self-esteem, creativity, performance, work satisfaction, organizational embeddedness, and fairness.'),
            _entry(253, 270, 'mechanism',
                   'Thwarted belongingness through rejection, deprivation, or exclusion is associated with defensive/aggressive behavior, lower prosocial behavior, impaired cognition, distrust, loneliness, anxiety, and other negative reactions.'),
            _entry(253, 270, 'boundary_condition',
                   'The chapter discusses competing mediation and moderation explanations involving loneliness, emotion, hostile cognition, team size, leader empathy, fairness, and social resources.'),
            _entry(254, 271, 'criticism',
                   'The evaluation notes inconsistent effects of deprivation on positive and negative affect and cognition and calls for stronger evidence on the underlying mechanism.'),
            _entry(255, 272, 'criticism',
                   'The chapter identifies student and clinical concentration, possible unconscious/complex processes, and the need for systematic models and better-balanced experiments as limitations.'),
            _entry(256, 273, 'measurement',
                   'The key-measures section lists SOBI-P (18 items), NTBS (10), the INQ belongingness subscale (9), and GBS (12); item wording is intentionally not copied.'),
            _entry(257, 274, 'boundary_condition',
                   'The management discussion extends belongingness to work outcomes but warns that excessive conformity pressure can suppress voice and creativity, so belonging should be balanced with distinctiveness.'),
        ],
    },
    'neo-institutional-theory': {
        'coding': {
            'definition': (
                'Neo-institutional theory explains organizational stability, conformity, and variation '
                'through socially constructed institutional environments that impose legitimacy pressures '
                'and encourage isomorphism, while later work also emphasizes organizational agency and heterogeneity.'
            ),
            'constructs': [
                'institutional environment and organizational field',
                'institutional pressure and institutional legitimacy',
                'coercive, mimetic, and normative isomorphism',
                'regulative, normative, and cognitive institutional pillars',
                'pragmatic, moral, and cognitive legitimacy',
                'symbolic versus substantive organizational performance',
                'decoupling and selective coupling',
                'institutional logics, institutional entrepreneurship, institutional work, and institutional complexity',
                'organizational agency and heterogeneity',
            ],
            'mechanisms': [
                'coercive isomorphism spreads through laws, regulations, and powerful state or government actors',
                'mimetic processes lead organizations to imitate high-performing organizations under uncertainty',
                'normative pressures diffuse through professional similarity, networks, and shared expectations',
                'institutional conformity can increase legitimacy and symbolic performance while reducing operational efficiency or substantive performance',
                'decoupling can satisfy external legitimacy demands while preserving internal efficiency',
                'organizations respond strategically to institutional pressure through acquiescence, compromise, avoidance, defiance, or manipulation',
                'institutional entrepreneurship and institutional work allow actors to create, maintain, or disrupt institutions',
            ],
            'boundary_conditions': [
                'The relevant institutional field, level, and set of actors must be specified; measurement is highly context dependent.',
                'Institutional responses vary with uncertainty, competing logics, organizational identity, governance, power distribution, and stakeholder networks.',
                'The chapter distinguishes single or homogeneous pressures from multiple and competing institutional logics.',
                'The theory has expanded from explaining organizational similarity to explaining agency, heterogeneity, institutional change, and micro-level experience.',
            ],
            'criticisms': [
                'The chapter reports criticism that neo-institutional work can overemphasize coercive state pressure and understate social norms and values.',
                'Without examining motives, imitation cannot be clearly distinguished as rational learning versus institutional pressure.',
                'Rational criteria for compliance or change can leave the theory dependent on a rational-choice perspective and underdeveloped micro-foundations.',
                'The chapter points to insufficient attention to individual nonrational experience, emotion, and the motivations behind institutional action.',
            ],
            'measurement_scales': [
                {
                    'name': 'Coercive pressure operationalization',
                    'source': 'Mezias (1990)',
                    'metadata': 'Context-specific organizational-practice measure in Fortune 200 financial reporting; no universal item set is supplied.',
                    'status': 'chapter-reported operationalization; primary-source verification required',
                },
                {
                    'name': 'Mimetic process operationalization',
                    'source': 'Haunschild & Miner (1997)',
                    'metadata': 'Interorganizational imitation studied through outcome salience and uncertainty; chapter presents it as a context-specific measure.',
                    'status': 'chapter-reported operationalization; primary-source verification required',
                },
                {
                    'name': 'Normative pressure operationalization',
                    'source': 'Honig & Karlsson (2004)',
                    'metadata': 'Institutional forces in written business plans; no universal item set is supplied.',
                    'status': 'chapter-reported operationalization; primary-source verification required',
                },
                {
                    'name': 'Institutional logics operationalizations',
                    'source': 'Marquis & Lounsbury (2007); Lounsbury (2007); Greenwood et al. (2010); Dunn & Jones (2010)',
                    'metadata': 'The chapter lists national/local, performance/trustee, market/religion/local, and care/science logic comparisons; coding is case and field specific.',
                    'status': 'chapter-reported operationalization; primary-source verification required',
                },
            ],
            'methods': [
                'Organizational-field and institutional-diffusion studies using archival, historical, and comparative evidence.',
                'Qualitative process and case studies of institutional entrepreneurship, institutional work, and institutional change.',
                'Context-specific quantitative operationalization of coercive, mimetic, normative, and logic pressures.',
                'Meta-analysis and multi-level or micro-foundational studies of institutional theory and organizational responses.',
            ],
            'cited_works': [
                'Meyer & Rowan (1977)',
                'DiMaggio & Powell (1983)',
                'Scott (1995)',
                'Suchman (1995)',
                'Oliver (1991)',
                'Lawrence & Suddaby (2006)',
                'Greenwood et al. (2011)',
                'Thornton, Ocasio, & Lounsbury (2012)',
            ],
        },
        'evidence': [
            _entry(258, 275, 'definition',
                   'The chapter traces neo-institutional theory to Meyer and Rowan (1977), later developed by DiMaggio and Powell, and positions it as an explanation of organizational-field stability and isomorphism.'),
            _entry(259, 276, 'construct',
                   'The theory emphasizes socially constructed institutional environments and extends beyond conformity to organizational agency and heterogeneity.'),
            _entry(260, 277, 'mechanism',
                   'The chapter defines organizational fields and distinguishes coercive, mimetic, and normative isomorphism; it also introduces pragmatic, moral, and cognitive legitimacy.'),
            _entry(260, 277, 'construct',
                   'Scott’s framework links regulative, normative, and cognitive institutional pillars to the three isomorphic mechanisms and organizational conformity.'),
            _entry(261, 278, 'mechanism',
                   'Empirical applications distinguish symbolic performance gains in social evaluation, naming, and status from possible reductions in operational efficiency and substantive performance.'),
            _entry(262, 279, 'mechanism',
                   'Institutional entrepreneurship and institutional work describe how actors create, maintain, or disrupt institutions; decoupling and five strategic responses describe organizational agency under pressure.'),
            _entry(263, 280, 'boundary_condition',
                   'Institutional complexity and competing logics produce heterogeneous responses shaped by field structure, organizational identity, governance, power, and stakeholder networks.'),
            _entry(263, 280, 'criticism',
                   'The evaluation presents convergence and divergence as complementary sides of the theory: institutions constrain organizations, but organizations can respond to and reshape institutions.'),
            _entry(264, 281, 'criticism',
                   'The chapter reports concerns about overemphasis on coercive pressure, unclear motives behind imitation, rational-choice dependence, and weak micro-level attention to experience and emotion.'),
            _entry(264, 281, 'measurement',
                   'The measurement section states that coercive, mimetic, normative, and institutional-logic measures are highly contextualized and must be designed for the specific object and setting.'),
            _entry(265, 282, 'measurement',
                   'The chapter lists case-specific operationalizations for coercive pressure, imitation, normative pressure, and competing institutional logics; these are metadata records, not universal scales.'),
            _entry(266, 283, 'citation',
                   'The classic-works and management sections include Meyer and Rowan, DiMaggio and Powell, Scott, institutional logics, institutional work, and agency-oriented extensions.'),
        ],
    },
    'organizational-learning-theory': {
        'coding': {
            'definition': (
                'Organizational learning theory treats collective learning as a time-dependent process and '
                'outcome through which individual and group experience is transferred, interpreted, stored, '
                'and used in organizational processes and structures to respond to uncertainty and support development.'
            ),
            'constructs': [
                'individual, group, and organizational learning levels',
                'single-loop, double-loop, and triple-loop learning',
                'learning process and learning outcome',
                'organizational memory, knowledge acquisition, sharing, interpretation, and retention',
                'exploratory and exploitative learning',
                'learning over time, forgetting, and knowledge depreciation',
                'social, cultural, political, power, and cognitive dimensions',
                'organizational learning, adaptation, learning organization, and innovation',
            ],
            'mechanisms': [
                'individual and group experience is transferred into organizational routines, processes, structures, and memory',
                'single-loop learning changes behavior to preserve stability, double-loop learning revises mental models, and triple-loop learning creates new operating patterns',
                'uncertainty, conflict, error, technological change, and competitive pressure stimulate organizational learning',
                'prior behavior can generate learning insights that subsequently change future behavior and routines',
                'knowledge sharing and organizational memory connect learning to performance, innovation, strategy, and capability',
                'leadership style, organizational culture, and social context influence learning processes and outcomes',
            ],
            'boundary_conditions': [
                'Organizational learning is continuous, stage dependent, and dynamic rather than a one-time intervention.',
                'The level of analysis and learning type must be specified; individual learning is necessary but not equivalent to organizational learning.',
                'Power, politics, culture, cognition, time, forgetting, and knowledge depreciation affect whether learning is retained and used.',
                'The chapter discusses individual, organizational, cross-organizational, strategic, innovation, and leadership contexts.',
            ],
            'criticisms': [
                'Definitions remain contested and the concept is broad across disciplines.',
                'Much research focuses on learning outcomes while underrepresenting the process complexity through which learning occurs.',
                'Individual learning is an imperfect proxy for organizational learning, and high-level learning can be difficult to explain.',
                'The boundaries between organizational learning, adaptation, learning organizations, and innovation remain blurred.',
                'Experience-based knowledge can depreciate as the environment changes, creating a fit problem for organizational memory.',
            ],
            'measurement_scales': [
                {
                    'name': 'Exploratory Learning and Exploitative Learning Measure',
                    'source': 'Li, Chen, Liu, & Peng (2014)',
                    'metadata': 'Five dimensions and 10 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Stakeholder-focused Organizational Learning',
                    'source': 'Mena & Chabowski (2015)',
                    'metadata': 'Nine dimensions and 40 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Explorative and Exploitative Learning Measure',
                    'source': 'Chung, Yang, & Huang (2015)',
                    'metadata': 'Two dimensions and 12 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
            ],
            'methods': [
                'Longitudinal and time-sensitive studies of learning, forgetting, memory, and adaptation.',
                'Individual-, group-, and organization-level surveys and multilevel analysis.',
                'Mediation tests linking leadership, innovation, knowledge transfer, organizational learning, and performance.',
                'Case, process, and cross-organizational studies of routines, strategy, culture, and institutional learning.',
            ],
            'cited_works': [
                'Argyris & Schön (1978, 1997)',
                'Fiol & Lyles (1985)',
                'Huber (1991)',
                'Dodgson (1993)',
                'Easterby-Smith, Crossan, & Nicolini (2000)',
                'Schilling & Kluge (2009)',
                'Yukl (2009)',
            ],
        },
        'evidence': [
            _entry(267, 284, 'definition',
                   'The chapter traces organizational learning to Argyris and Schön and identifies collective learning by organizational members as the common core of competing definitions.'),
            _entry(268, 285, 'boundary_condition',
                   'Organizational learning is described as a continuous, stage-dependent, and dynamic process and outcome that helps organizations respond to changing external environments.'),
            _entry(269, 286, 'construct',
                   'The chapter distinguishes individual, group, and organizational levels and single-loop, double-loop, and triple-loop learning; individual learning is not simply summed into organizational learning.'),
            _entry(269, 286, 'mechanism',
                   'Group and individual learning experiences are transferred into organizational processes and structures, while social, political, power, cultural, and cognitive factors shape the process.'),
            _entry(270, 287, 'boundary_condition',
                   'The chapter differentiates organizational learning from individual learning, organizational adaptation, learning organizations, and innovation and notes that knowledge must be shared across members and departments.'),
            _entry(271, 288, 'mechanism',
                   'Applications link organizational learning with strategic transformation, innovation, leadership, routines, knowledge transfer, and performance through proposed mediating processes.'),
            _entry(271, 288, 'criticism',
                   'The chapter reports that research on antecedents is more developed than research on diverse organizational outcomes and that the learning–innovation boundary remains blurred.'),
            _entry(272, 289, 'criticism',
                   'The evaluation emphasizes time, forgetting, and knowledge depreciation and criticizes outcome-focused analysis that overlooks learning-process complexity.'),
            _entry(272, 289, 'measurement',
                   'The key-measures section lists exploratory/exploitative learning, stakeholder-focused learning, and a second exploratory/exploitative measure with dimensions and item counts only.'),
            _entry(273, 290, 'citation',
                   'The classic-works section includes Argyris and Schön, Dodgson, Fiol and Lyles, Huber, Easterby-Smith et al., Schilling and Kluge, and Yukl.'),
            _entry(274, 291, 'boundary_condition',
                   'The management discussion stresses collective knowledge acquisition, sharing, interpretation, retention, and leadership support rather than treating learning as an individual-only activity.'),
        ],
    },
    'person-environment-fit': {
        'coding': {
            'definition': (
                'Person–Environment Fit theory explains attitudes and behavior as products of compatibility '
                'between a person and relevant environmental levels, occurring when one side supplies the other’s '
                'needs or when person and environment share compatible characteristics.'
            ),
            'constructs': [
                'person–organization, person–group, person–job, person–supervisor, and person–vocation fit',
                'supplementary/congruent fit and complementary fit',
                'demands–abilities fit and needs–supplies fit',
                'objective and perceived fit',
                'attraction–selection–attrition (ASA) and dynamic fit processes',
                'individual, organizational, social-cultural, and work-environment antecedents',
                'job satisfaction, commitment, performance, well-being, adaptation, retention, stress, and career success',
            ],
            'mechanisms': [
                'person and environment jointly shape attitudes and behavior rather than either side acting alone',
                'attraction draws people toward environments that satisfy needs, selection chooses people who support organizational goals, and attrition removes persistent misfit',
                'work experience can change both person and environment and thereby alter objective and perceived fit',
                'job crafting allows proactive employees to modify tasks, work organization, or relationships to improve fit',
                'recruitment, selection, socialization, training, feedback, and organizational values shape perceived person–environment fit',
            ],
            'boundary_conditions': [
                'The relevant environmental level and fit type must be specified; different fits predict different outcomes.',
                'Fit is dynamic and can change with experience, organizational change, job crafting, exchange, and attrition.',
                'Culture moderates the relative importance of person–job versus person–organization fit; the chapter contrasts individualistic and collectivist settings and identifies China-specific themes.',
                'The distinction between demands–abilities and needs–supplies fit affects the construct and measurement strategy.',
            ],
            'criticisms': [
                'The chapter reports disagreement about the construct’s dimensions, content, measurement indicators, and overall analytical framework.',
                'Antecedent research is limited and many outcome studies focus on individual-level satisfaction, commitment, performance, and stress.',
                'Dynamic interaction between person and environment remains underexplored relative to static fit assessments.',
                'The many fit dimensions and cultural variations make cross-study comparison and universal measurement difficult.',
            ],
            'measurement_scales': [
                {
                    'name': 'Person–Organization Fit measure',
                    'source': 'Saks & Ashforth (1997)',
                    'metadata': 'Four items as listed in the chapter; longitudinal applicant/work-outcome context.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'P–O, Needs–Supplies, and Demands–Abilities Fit measures',
                    'source': 'Cable & DeRue (2002)',
                    'metadata': 'Three items for each of P–O fit, needs–supplies fit, and demands–abilities fit.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Person–Environment Fit three-dimensional model',
                    'source': 'Livingstone, Nelson, & Barr (1997)',
                    'metadata': 'Five indicators across person, environment, and outcome dimensions as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Person–Supervisor Fit measure',
                    'source': 'Nolan & Morley (2014)',
                    'metadata': 'Three items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
            ],
            'methods': [
                'Longitudinal studies of applicant perceptions, socialization, fit change, and work outcomes.',
                'Survey and profile-based measurement of multiple fit dimensions and needs/supplies or demands/abilities compatibility.',
                'Cross-cultural comparisons and meta-analysis of person–job, person–organization, person–group, and person–supervisor fit.',
                'Organizational case and field applications involving recruitment, selection, training, job crafting, and expatriate adjustment.',
            ],
            'cited_works': [
                'Lewin (1935, 1951)',
                'Murray (1938, 1951)',
                'Schneider (1987)',
                'Chatman (1989, 1991)',
                'Muchinsky & Monahan (1987)',
                'Kristof (1996)',
                'Kristof-Brown et al. (2005)',
                'Cable & DeRue (2002)',
            ],
        },
        'evidence': [
            _entry(276, 293, 'definition',
                   'The chapter traces person–environment fit from Parsons, Murray, and Lewin and highlights Schneider’s attraction–selection–attrition model as a major organizational development.'),
            _entry(277, 294, 'mechanism',
                   'ASA explains attraction, selection, and attrition, while Chatman’s person–organization model emphasizes value congruence and Pervin frames satisfaction and performance as dynamic fit processes.'),
            _entry(278, 295, 'construct',
                   'The chapter distinguishes person–organization, person–group, person–job, person–supervisor, and person–vocation fit and separates congruent from complementary fit.'),
            _entry(278, 295, 'construct',
                   'Complementary fit is divided into demands–abilities and needs–supplies fit; the chapter links different fit dimensions to different attitudinal, behavioral, and team outcomes.'),
            _entry(279, 296, 'mechanism',
                   'Fit is described as a dynamic process involving attraction, selection, exchange, accommodation, attrition, and job crafting rather than a fixed person or environment property.'),
            _entry(279, 296, 'mechanism',
                   'Recruitment, selection, training, socialization, organizational values, and guidance can communicate norms and improve perceived fit.'),
            _entry(280, 297, 'boundary_condition',
                   'Culture moderates fit priorities; the chapter contrasts person–job and person–organization fit across individualistic and collectivist settings and reports five China-specific themes.'),
            _entry(280, 297, 'construct',
                   'Applications associate fit with satisfaction, lower stress, adaptation, retention, performance, commitment, and career success across multiple fit dimensions.'),
            _entry(281, 298, 'criticism',
                   'The evaluation reports disagreement over content, dimensions, measurement, antecedents, and the lack of a complete dynamic person–environment interaction framework.'),
            _entry(281, 298, 'measurement',
                   'The key-measures section lists P–O, needs–supplies, demands–abilities, P–E, and P–S measures with item/indicator counts only; wording is not copied.'),
            _entry(282, 299, 'citation',
                   'The classic-works section includes Lewin, Schneider, Edwards and Cooper, Kristof-Brown et al., Cable and DeRue, Chuang et al., and related fit scholarship.'),
            _entry(283, 300, 'boundary_condition',
                   'The management discussion applies fit to recruitment, socialization, feedback, team cooperation, career development, and work–family support while retaining the need to specify fit dimensions.'),
        ],
    },
    'population-ecology-theory': {
        'coding': {
            'definition': (
                'Population ecology theory applies evolutionary ecology to organizations by treating similar '
                'organizations as populations shaped by environmental selection, variation, and retention, '
                'with survival and change analyzed at the population rather than only the individual-organization level.'
            ),
            'constructs': [
                'organizational population and population boundaries',
                'variation, environmental selection, and retention',
                'structural inertia and organizational adaptation',
                'organizational founding/natality and mortality',
                'population density, competition, niche, carrying capacity, and resource dependence',
                'organizational legitimacy, heterogeneity, and ecosystem relations',
                'population development and organizational life cycle',
            ],
            'mechanisms': [
                'organizational innovation creates variation, environmental conditions select organizations, and survival retains selected forms',
                'structural inertia limits organizations’ ability to learn or change structures, increasing the role of environmental selection',
                'resource scarcity, competition, population density, and carrying capacity shape founding, survival, and mortality',
                'niche positioning and dependence on material/social environments connect organizational populations with market and ecosystem change',
                'government policy, legitimacy, entry costs, and strategic ecosystem relationships alter population dynamics',
            ],
            'boundary_conditions': [
                'A population requires a defensible definition of similar goals, norms, boundaries, and material/social resource dependence.',
                'The theory emphasizes population-level analysis, although organization-level events such as founding and death are used as indicators.',
                'Business ecosystem and industry applications require attention to population, niche, density, competition, and environmental levels together.',
                'Diverse organizations may belong to multiple or unclear populations, creating a classification boundary problem.',
            ],
            'criticisms': [
                'The chapter identifies the difficulty of assigning increasingly diverse organizations to one or more populations.',
                'Mainstream theory lacks a satisfactory model of common population change over time.',
                'Lotka–Volterra modeling is described as a simplified treatment that reduces population development to numerical fluctuation.',
                'The theory’s macro emphasis can leave organizational agency and internal adaptation less visible than environmental selection.',
            ],
            'measurement_scales': [
                {
                    'name': 'Organizational natality',
                    'source': 'Hannan & Freeman (1989); Delacroix & Carroll (1983)',
                    'metadata': 'Operational definition: number of organizational foundings; measurement content: approved registration date.',
                    'status': 'chapter-reported operationalization; primary-source verification required',
                },
                {
                    'name': 'Organizational mortality',
                    'source': 'Hannan & Freeman (1989); Amburgey & Rao (1996)',
                    'metadata': 'Operational definition: number of organizational deaths; measurement content: approved cancellation/deregistration date.',
                    'status': 'chapter-reported operationalization; primary-source verification required',
                },
                {
                    'name': 'Population density',
                    'source': 'Agarwal & Gort (2002)',
                    'metadata': 'Operational definition: industry population density; measurement content: total organizations divided by total sales as listed in the chapter.',
                    'status': 'chapter-reported operationalization; primary-source verification required',
                },
                {
                    'name': 'Satisfaction with Information Content Measure',
                    'source': 'Doll & Torkzadeh (1988)',
                    'metadata': 'One dimension and three items are listed in the chapter; its conceptual fit with population-ecology variables requires independent review.',
                    'status': 'chapter-reported metadata; conceptual scope check and primary-source verification required',
                },
                {
                    'name': 'Information Satisfaction Measure',
                    'source': 'Wixom & Todd (2005)',
                    'metadata': 'Seven dimensions and 49 items are listed in the chapter; its conceptual fit with population-ecology variables requires independent review.',
                    'status': 'chapter-reported metadata; conceptual scope check and primary-source verification required',
                },
            ],
            'methods': [
                'Longitudinal archival and event-history analysis of organizational founding, survival, mortality, and density.',
                'Secondary-data and interview studies of organizational populations, legitimacy, inertia, and innovation.',
                'Lotka–Volterra, density, niche, carrying-capacity, and competition models.',
                'Industry, market, product, and business-ecosystem comparative analysis.',
            ],
            'cited_works': [
                'Hannan & Freeman (1977, 1984, 1989)',
                'Carroll (1984)',
                'Freeman & Hannan (1983)',
                'Amburgey & Rao (1996)',
                'Lomi (1995)',
                'Betton & Dess (1985)',
                'Iansiti & Levien (2004)',
            ],
        },
        'evidence': [
            _entry(284, 301, 'definition',
                   'The chapter traces organizational population ecology to Hannan and Freeman and defines it as an ecological application that analyzes similar organizations and their environment.'),
            _entry(285, 302, 'construct',
                   'A population is described through similar organizational goals, norms, boundaries, and dependence on shared material and social resources; the theory emphasizes diversity and adaptation at population level.'),
            _entry(285, 302, 'mechanism',
                   'The chapter frames population ecology through variation, environmental selection, and retention, corresponding to organizational innovation, environmental choice, and survival.'),
            _entry(286, 303, 'mechanism',
                   'Structural inertia limits organizational learning and makes environmental selection central; mortality, natality, Lotka–Volterra development, and density/competition indicators are discussed.'),
            _entry(286, 303, 'boundary_condition',
                   'Population similarity is judged by shared material and environmental dependence, and later work connects organizational populations with resource scarcity, competition, niches, and business ecosystems.'),
            _entry(286, 303, 'method',
                   'Cited empirical applications use secondary data and interviews to study legitimacy, internal consistency, population density, carrying capacity, competition, and organizational founding.'),
            _entry(287, 304, 'method',
                   'Applications extend to industry ecology, product strategy, government policy, and private versus formal transnational regulatory organizations using historical and ecosystem evidence.'),
            _entry(287, 304, 'criticism',
                   'The evaluation presents the macro ecological contribution but notes the challenge of classifying diverse organizations into populations and the lack of a model for common population change.'),
            _entry(288, 305, 'measurement',
                   'The chapter lists information-satisfaction records and begins operationalizations for organizational natality; the information measures are retained as chapter-reported metadata with a conceptual-scope warning.'),
            _entry(289, 306, 'measurement',
                   'Key variables define natality, mortality, and population density using founding/cancellation registration dates and organization-count or sales-based density indicators.'),
            _entry(289, 306, 'citation',
                   'The classic-works section includes Hannan and Freeman, Carroll, Freeman and Hannan, Amburgey and Rao, Betton and Dess, and Lomi.'),
            _entry(290, 307, 'boundary_condition',
                   'The management discussion emphasizes ecosystem fit, distinct competitive capabilities, open networks, niches, and changing innovation paths rather than relying on today’s market logic for tomorrow’s environment.'),
        ],
    },
    'regulatory-focus-theory': {
        'coding': {
            'definition': (
                'Regulatory focus theory explains self-regulation as distinct promotion- and prevention-focused '
                'ways of approaching desired end states and avoiding undesired end states, with strategy choice '
                'shaped by goals, self-guides, affect, personality, and context.'
            ),
            'constructs': [
                'regulatory focus and self-regulation',
                'promotion focus, ideal self, gains/non-gains, eagerness, and hits',
                'prevention focus, ought self, nonlosses/losses, vigilance, and correct rejections',
                'strategic means, approach/avoidance, and regulatory fit',
                'promotion and prevention as independent systems rather than opposite ends of one continuum',
                'regulatory-focus plasticity, stability, and context/personality influences',
                'goal attainment, emotion, risk, uncertainty, decision speed, and performance',
            ],
            'mechanisms': [
                'promotion-focused self-regulation reduces the gap between current and ideal states through eager gain-seeking strategies',
                'prevention-focused self-regulation reduces the gap between current and ought states through vigilant loss-avoidance strategies',
                'promotion success/failure is associated with different affective experiences than prevention success/failure',
                'promotion and prevention are managed by partly independent systems and can both be high, both low, or asymmetrically high',
                'values, norms, past performance, interpersonal interaction, personality, and organizational context shape regulatory-focus choice',
            ],
            'boundary_conditions': [
                'Promotion and prevention are not a single continuum; their correlation is described as small and both can coexist.',
                'Regulatory focus is more plastic than a stable personality trait but more stable than a momentary emotion.',
                'The same goal can elicit different strategies across people or contexts, and a person’s balance can change over time and situations.',
                'The chapter applies the theory to organizational management, work redesign, entrepreneurship, leadership, and strategic regulatory framing.',
            ],
            'criticisms': [
                'The theory does not fully explain why different people choose different approach or avoidance strategies for the same goal.',
                'Promotion and prevention can coexist and fluctuate with person and environment, creating mixed or unclear explanations.',
                'The chapter says the theory does not adequately explain within-person strategy shifts across time during the same event.',
                'The chapter suggests combining sensitivity theory with regulatory focus to better explain motivational differences.',
            ],
            'measurement_scales': [
                {
                    'name': 'Selves Questionnaire',
                    'source': 'Higgins, Roney, Crowe, & Hymes (1994)',
                    'metadata': 'Two dimensions as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Self-guide Strength Measure',
                    'source': 'Higgins, Shah, & Friedman (1997)',
                    'metadata': 'Two dimensions as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'Regulatory Focus Questionnaire',
                    'source': 'Higgins et al. (2001)',
                    'metadata': 'Two dimensions and 11 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
                {
                    'name': 'General Regulatory Focus Measure',
                    'source': 'Lockwood, Jordan, & Kunda (2002)',
                    'metadata': 'Two dimensions and 18 items as listed in the chapter.',
                    'status': 'chapter-reported metadata; primary-source verification required',
                },
            ],
            'methods': [
                'Questionnaire-based measurement of promotion and prevention self-regulation and self-guides.',
                'Experimental and psychological-situation studies of goal attainment, affect, approach/avoidance, and regulatory fit.',
                'Meta-analysis and longitudinal/context-sensitive research on the independence and stability of the two foci.',
                'Organizational field applications involving leadership, work redesign, entrepreneurship, recruitment, and strategic framing.',
            ],
            'cited_works': [
                'Higgins (1987, 1997, 2000, 2012)',
                'Higgins & Tykocinski (1992)',
                'Higgins et al. (1994, 2001)',
                'Crowe & Higgins (1997)',
                'Brockner & Higgins (2001)',
                'Lockwood, Jordan, & Kunda (2002)',
                'Lanaj et al. (2012)',
            ],
        },
        'evidence': [
            _entry(291, 308, 'definition',
                   'The chapter traces regulatory focus theory to Higgins and defines it as a way of explaining how people pursue work-task goals through particular self-regulatory tendencies.'),
            _entry(292, 309, 'definition',
                   'Regulatory focus concerns approaching desired end states and avoiding undesired end states; the theory distinguishes promotion and prevention motives.'),
            _entry(293, 310, 'mechanism',
                   'Promotion focus is tied to the ideal self, current-to-ideal discrepancy, gains/non-gains, eagerness, and gain-seeking action.'),
            _entry(293, 310, 'mechanism',
                   'Prevention focus is tied to the ought self, current-to-ought discrepancy, nonlosses/losses, vigilance, rule adherence, and error avoidance.'),
            _entry(294, 311, 'construct',
                   'The two foci are described as independent strategic systems rather than opposite ends of one continuum; individuals can be high or low on either or both.'),
            _entry(294, 311, 'boundary_condition',
                   'Personality, values, norms, past performance, interpersonal interaction, and organizational context can shift strategy choice; regulatory focus is plastic but not momentary.'),
            _entry(294, 311, 'criticism',
                   'The evaluation notes that the theory does not fully explain why people choose different strategies for identical goals and suggests integrating sensitivity theory.'),
            _entry(295, 312, 'criticism',
                   'The chapter reports that simultaneous promotion and prevention, changing person/environment conditions, and unmodeled within-event changes can create mixed explanations.'),
            _entry(295, 312, 'measurement',
                   'The key-measures section lists the Selves Questionnaire, Self-guide Strength Measure, Regulatory Focus Questionnaire, and General Regulatory Focus Measure with dimensions and item counts only.'),
            _entry(296, 313, 'citation',
                   'The classic-works section includes Higgins, self-discrepancy and regulatory-focus papers, Crowe and Higgins, Brockner and Higgins, and Lockwood et al.'),
            _entry(297, 314, 'boundary_condition',
                   'The management discussion differentiates support for high-promotion/high-prevention combinations, risk-control needs, goal communication, performance feedback, entrepreneurship, and strategic regulatory framing.'),
        ],
    },
}


def _blank(value):
    return value in (None, '', [])


def _evidence_key(entry):
    return (
        entry.get('printed_page'),
        entry.get('pdf_page'),
        entry.get('kind'),
        entry.get('quote_or_note'),
    )


def apply_updates(payload, updates=EVIDENCE_UPDATES):
    """Merge explicit updates without overwriting non-empty user coding."""
    rows = {
        row.get('theory_id'): row
        for row in payload.get('chapters', [])
        if isinstance(row, dict) and row.get('theory_id')
    }
    changed = []
    for theory_id, update in updates.items():
        row = rows.get(theory_id)
        if row is None:
            raise KeyError('theory not found in evidence queue: %s' % theory_id)
        coding = row.setdefault('coding', {})
        for field, value in (update.get('coding') or {}).items():
            if _blank(coding.get(field)):
                coding[field] = deepcopy(value)
        status = coding.get('status', 'needs_human_coding')
        if status == 'needs_human_coding':
            coding['status'] = 'partially_human_coded'
        flags = set(row.get('review_flags') or [])
        flags.discard(REMOVED_PENDING_FLAG)
        flags.update({PARTIAL_REVIEW_FLAG, PRIMARY_SOURCE_REVIEW_FLAG})
        row['review_flags'] = sorted(flags)
        evidence = row.setdefault('evidence', [])
        existing = {_evidence_key(item) for item in evidence if isinstance(item, dict)}
        added = 0
        for entry in update.get('evidence') or []:
            key = _evidence_key(entry)
            if key not in existing:
                evidence.append(deepcopy(entry))
                existing.add(key)
                added += 1
        changed.append({'theory_id': theory_id, 'evidence_added': added})
    return changed


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _write(path, payload):
    target = Path(path)
    temporary = target.with_suffix(target.suffix + '.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(target)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    # Refresh locators first; build_queue preserves existing coding/evidence.
    build_queue(output_path=args.output)
    payload = _read(args.output)
    changed = apply_updates(payload)
    _write(args.output, payload)
    print('updated', args.output)
    print('chapters_coded:', len(changed))
    print('evidence_added:', sum(item['evidence_added'] for item in changed))
    print('status:', 'partially_human_coded')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
