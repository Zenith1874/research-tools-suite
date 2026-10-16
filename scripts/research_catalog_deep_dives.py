# -*- coding: utf-8 -*-
"""Long-form analysis for catalog theories.

The catalog's base fields answer "what is this theory". They do not answer the
questions a researcher actually has when deciding whether to build on it:

* what problem was the field stuck on when this was written;
* how the argument actually runs, step by step;
* which debates about it are still open;
* which of its limits are theoretical, which are measurement artefacts, and
  which are simply features of the era it was written in;
* what still holds today and what has been overtaken.

A deep dive is written analysis, not extracted text. Nothing here is copied from
any book, database, or article; where a claim belongs to a specific author it is
attributed inline the way a review article would attribute it, and the reader is
still expected to go to the primary source before citing.

Coverage is deliberately partial and explicit: a theory either has a deep dive
or it does not, and the API reports which, so the UI never implies an analysis
exists where none was written.
"""

DEEP_DIVE_STATUS = 'authored_analysis'


def P(en, zh):
    """One paragraph, in both languages."""
    return {'en': en, 'zh': zh}


def Pos(holder, claim, claim_zh):
    return {'holder': holder, 'claim': claim, 'claim_zh': claim_zh}


def Debate(name, name_zh, positions, status, status_zh):
    return {'name': name, 'name_zh': name_zh, 'positions': list(positions),
            'status': status, 'status_zh': status_zh}


def D(theory_id, era, era_zh, situation=(), argument=(), development=(),
      debates=(), theoretical=(), empirical=(), temporal=(), today=()):
    return theory_id, {
        'status': DEEP_DIVE_STATUS,
        'era': era, 'era_zh': era_zh,
        'situation': list(situation),
        'argument': list(argument),
        'development': list(development),
        'debates': list(debates),
        'limitations': {
            'theoretical': list(theoretical),
            'empirical': list(empirical),
            'temporal': list(temporal),
        },
        'today': list(today),
    }


DEEP_DIVES = dict([

    # ------------------------------------------------------------------- RBV
    D('resource-based-view',
      era='Formulated 1984-1991; consolidated and contested through the 1990s and 2000s.',
      era_zh='1984—1991 年成形，1990 至 2000 年代在争论中被巩固。',
      situation=[
        P('By the late 1970s strategic management had adopted industry structure as its explanatory centre. If sustained profit came from industry position and mobility barriers, then the interesting variation was between industries, and the firm itself was close to a black box.',
          '到 1970 年代末，战略管理把产业结构当作解释的中心。如果持续盈利来自产业位置与流动壁垒，那么值得解释的差异就在产业之间，企业本身近乎一个黑箱。'),
        P('That position could not account for a stubborn empirical fact: profitability differences within an industry were routinely larger than differences between industries. Firms facing the same competitive forces were not earning the same returns, and the dominant framework had no vocabulary for why.',
          '但这一立场无法解释一个顽固的经验事实：产业内部的盈利差异经常大于产业之间的差异。面对同样竞争力量的企业回报并不相同，而主流框架没有词汇解释为什么。'),
        P('The resource-based view was the answer to that specific gap. It relocated the source of advantage from the firm position in a market to the bundle of resources the firm controls, using an economics of rents that already existed but had not been pointed at strategy.',
          '资源基础观正是对这一缺口的回答。它把优势的来源从企业在市场中的位置，转移到企业所控制的资源束上，所依据的租金经济学此前已经存在，只是尚未被用于战略问题。'),
      ],
      argument=[
        P('The argument runs in two moves. First, assume resources are heterogeneously distributed across firms and imperfectly mobile between them. Without both assumptions the argument collapses: if every firm can assemble the same bundle, no bundle can sustain an advantage.',
          '论证分两步。第一步，假定资源在企业之间分布异质、且难以完全流动。缺少任何一条假定，论证即告瓦解：若人人都能凑齐同样的资源束，任何资源束都无法维持优势。'),
        P('Second, ask what property a resource must have to sustain rather than merely create an advantage. The answer is the familiar VRIN screen, but the load-bearing element is inimitability, and inimitability is itself explained by isolating mechanisms: causal ambiguity, path dependence, social complexity, and time-compression diseconomies.',
          '第二步，追问一项资源要具备什么性质才能"维持"而非仅仅"创造"优势。答案就是熟悉的 VRIN 筛子，但真正承重的是难以模仿性，而它又由隔离机制来解释：因果模糊、路径依赖、社会复杂性与时间压缩不经济。'),
        P('The framework is therefore an equilibrium argument about why differences persist, not a recipe for creating them. Read as a recipe it disappoints, and much of the criticism it has attracted comes from reading it that way.',
          '因此该框架是关于"差异为何持续存在"的均衡论证，而不是"如何制造差异"的操作指南。把它当作指南来读必然失望，而它所招致的许多批评正源于这种读法。'),
      ],
      development=[
        P('The dynamic capabilities view asked how a firm renews its resource base when markets shift, moving the emphasis from possession to sensing, seizing, and reconfiguring. Whether this is a separate theory or a special case of the resource-based view applied to disequilibrium remains genuinely contested.',
          '动态能力观追问企业在市场变动时如何更新其资源基础，把重点从"拥有"转向感知、把握与重构。它究竟是一个独立理论，还是资源基础观在非均衡状态下的特例，至今仍有真实分歧。'),
        P('The knowledge-based view narrowed the resource of interest to knowledge and derived the existence of the firm from knowledge integration. The relational view pushed in the opposite direction, locating rents in ties between firms - alliances, specialized supplier relationships, joint routines - rather than inside any one of them.',
          '知识基础观把关注的资源收窄为知识，并由知识整合推导出企业存在的理由。关系观则朝相反方向推进，把租金定位在企业"之间"的联结——联盟、专用化供应商关系、共同惯例——而非任何单个企业内部。'),
      ],
      debates=[
        Debate('Is the core claim tautological?', '核心命题是否同义反复？',
               [Pos('Priem & Butler (2001)',
                    'If a valuable resource is identified by the advantage it produces, the proposition that valuable resources produce advantage cannot be falsified.',
                    '若"有价值的资源"是由它带来的优势来识别的，那么"有价值的资源带来优势"就无法被证伪。'),
                Pos('Barney (2001)',
                    'Value is defined by the product market, independently of realized performance, so the framework is testable once value is operationalized exogenously.',
                    '价值由产品市场界定，独立于已实现绩效；只要价值被外生地操作化，框架就是可检验的。')],
               'Open. The exchange sharpened the requirement that value be measured independently of outcome, and applied work still frequently fails that requirement.',
               '未决。这场交锋确立了"价值须独立于结果来测量"的要求，而应用研究至今经常达不到这一要求。'),
        Debate('Is the framework static?', '框架是否是静态的？',
               [Pos('Critics',
                    'An equilibrium account cannot explain change, so it is silent about the environments managers actually face.',
                    '均衡式的解释无法说明变化，因而对管理者真正面对的环境无话可说。'),
                Pos('Defenders',
                    'Equilibrium logic is a tool for studying disequilibrium: comparing before-and-after states traces how competitive positions evolve.',
                    '均衡逻辑正是研究非均衡的工具：比较前后状态即可刻画竞争位置的演化。')],
               'Partly resolved by treating dynamic capabilities as making the movement between states explicit rather than replacing the account.',
               '部分化解：把动态能力理解为把状态之间的移动显式化，而非取代原有解释。'),
      ],
      theoretical=[
        P('Resource and capability are not cleanly separable, and the literature does not use the terms consistently. Conceptual drift across fields produced applications that contradict each other while claiming the same foundation.',
          '资源与能力无法干净地区分，文献对二者的用法也不一致。跨领域的概念漂移使得一些应用彼此矛盾，却都自称基于同一基础。'),
        P('The framework explains persistence better than genesis. Where the initial heterogeneity came from is largely pushed outside the model, into luck or history.',
          '框架对"优势为何延续"的解释强于对"优势如何产生"的解释。最初的异质性从何而来，基本被推到模型之外，归于运气或历史。'),
      ],
      empirical=[
        P('Resources are frequently proxied by outcomes - profitability, survival, market share - which makes it impossible to separate cause from consequence. A test that measures the resource through its effect cannot support the causal claim.',
          '资源常被用结果来代理——盈利、存续、市场份额——这使得原因与结果无法分离。以效果来测量资源的检验，无法支撑因果主张。'),
        P('Inimitability is asserted more often than it is demonstrated. Causal ambiguity is, by construction, as hard for the researcher to observe as it is for the rival to penetrate.',
          '难以模仿性被断言的次数远多于被证明的次数。因果模糊按其定义，对研究者的可观察性与对竞争者的可穿透性一样低。'),
      ],
      temporal=[
        P('The framework was built for firms with defensible boundaries competing in product markets. Its unit of analysis is a firm that owns its productive assets - an assumption that fits 1980s manufacturing and diversified corporations far better than platform businesses whose critical assets are user relationships and data they do not own outright.',
          '该框架针对的是边界清晰、在产品市场上竞争的企业。其分析单位是"拥有自身生产性资产"的企业——这一假定契合 1980 年代的制造业与多元化公司，却远不契合平台企业：后者的关键资产是用户关系与并不完全归其所有的数据。'),
        P('Imitation was assumed to be slow and costly. Where capability is embodied in software, in a model that can be distilled, or in staff who move freely, time-compression diseconomies bind much more weakly than they did when the argument was formulated.',
          '框架假定模仿是缓慢而昂贵的。当能力体现为软件、可被蒸馏的模型、或可自由流动的人员时，时间压缩不经济的约束力远弱于该论证成形之时。'),
        P('The theory predates the treatment of complementary assets held by other parties as a standing strategic condition. Firms that depend on a cloud provider, an app store, or a foundation model are subject to a form of resource dependence the original framework does not model.',
          '该理论早于"由他方掌握的互补性资产构成常态战略条件"这一议题。依赖云服务商、应用商店或基础模型的企业，正处在原框架未加建模的资源依赖之中。'),
      ],
      today=[
        P('The VRIN screen remains a disciplined way to ask why an advantage should last, and it still exposes strategies that rest on resources rivals can simply buy.',
          'VRIN 筛子仍是追问"优势为何应当持续"的一种严谨方式，也仍能揭穿那些建立在竞争者可直接购买的资源之上的战略。'),
        P('Its weakest point today is the boundary assumption. For questions about platforms, ecosystems, and AI capability, pair it with resource dependence theory or an ecosystem framing rather than using it alone.',
          '它今天最薄弱之处在于边界假定。研究平台、生态系统与 AI 能力时，应与资源依赖理论或生态系统视角配合使用，而不宜单独使用。'),
      ]),

    # ------------------------------------------------------------------- TAM
    D('technology-acceptance-model',
      era='Published 1989; extended through TAM2 (2000) and UTAUT (2003); heavily replicated into the 2010s.',
      era_zh='1989 年提出，经 TAM2（2000）与 UTAUT（2003）扩展，2010 年代仍被大量复制。',
      situation=[
        P('In the 1980s organizations were installing computers on individual desks and a large share of that investment went unused. The practical question was blunt: managers had bought systems that employees would not adopt, and there was no accepted way to predict which systems would be used.',
          '1980 年代，组织把计算机装上每张办公桌，而其中很大一部分投资闲置。现实问题很直白：管理者买来的系统员工不用，而当时没有公认的方法预测哪些系统会被使用。'),
        P('Social psychology already offered a general intention model, but it was too general to guide system design. The contribution was to specialize it: replace generic attitudes with two beliefs a designer can actually manipulate.',
          '社会心理学已提供了通用的意向模型，但过于笼统，无法指导系统设计。该模型的贡献在于将其专门化：用两个设计者可以实际干预的信念，替换掉笼统的态度变量。'),
      ],
      argument=[
        P('Two beliefs carry the model. Perceived usefulness is the belief that the system will improve performance; perceived ease of use is the belief that using it will not cost much effort. Ease of use also feeds usefulness, since a system that is easier to operate delivers more of its benefit.',
          '模型由两个信念承载。感知有用性是"系统会提升绩效"的信念，感知易用性是"使用它不会耗费太多精力"的信念。易用性还会反过来提升有用性，因为更易操作的系统能兑现更多收益。'),
        P('These beliefs form an intention, and intention predicts use. The chain is deliberately short, and that parsimony was the point: two constructs a designer can move, rather than a long list of factors a designer cannot.',
          '这两个信念形成行为意向，意向预测使用。这条链条被刻意做短，而这种简约正是其用意所在：给设计者两个可以推动的变量，而不是一长串无法干预的因素。'),
      ],
      development=[
        P('TAM2 added social influence and cognitive instrumental processes; UTAUT consolidated competing models into performance expectancy, effort expectancy, social influence, and facilitating conditions with individual-difference moderators.',
          'TAM2 加入社会影响与认知工具性过程；UTAUT 则把若干竞争模型整合为绩效期望、努力期望、社会影响与便利条件，并引入个体差异作为调节。'),
        P('The extension pattern itself became the subject of criticism: each addition raised explained variance while leaving the underlying causal account unchanged, which is accumulation rather than theoretical progress.',
          '这种"不断加变量"的扩展模式本身成为批评对象：每次添加都提高了解释方差，却没有改变底层的因果论述，这是累积而非理论进展。'),
      ],
      debates=[
        Debate('Has the model outlived its usefulness?', '该模型是否已完成历史使命？',
               [Pos('Critics',
                    'The relationships are established well enough that another replication with a new moderator contributes nothing; continued use crowds out better questions.',
                    '这些关系已被确立得足够充分，再做一次"换个调节变量"的复制毫无贡献；继续沿用反而挤占了更好的问题。'),
                Pos('Defenders',
                    'It remains a compact baseline against which a genuinely new adoption mechanism can be shown to add explanatory power.',
                    '它仍是一个简洁的基线，新的采纳机制只有相对于它才能被证明确有增量解释力。')],
               'Largely settled against new bare replications; the model survives as a control model rather than as a contribution in its own right.',
               '基本已有定论：不再接受纯粹的复制；该模型作为对照基线而非独立贡献而存续。'),
      ],
      theoretical=[
        P('It models an individual deciding in isolation. Organizational mandate, workflow interdependence, and the fact that one person adopting changes the value of adoption for others are all outside the model.',
          '它建模的是一个孤立个体的决策。组织强制、工作流上的相互依赖、以及"一个人采纳会改变他人采纳价值"这一事实，全都在模型之外。'),
        P('Usefulness and ease of use are treated as perceptions of a fixed artefact. Systems that adapt to the user, or that behave differently for different users, break that assumption.',
          '有用性与易用性被当作对一个固定人工物的感知。会随用户自适应、或对不同用户表现不同的系统，破坏了这一假定。'),
      ],
      empirical=[
        P('Self-reported use is the usual dependent variable and is a weak proxy for observed use; correlations between the two are far from perfect and vary with the setting.',
          '因变量通常是自报使用量，而它是对实际使用的弱代理；二者相关远非完美，且随情境变化。'),
        P('Predictors and outcome are typically collected in one questionnaire at one moment, which inflates the relationships through common method variance.',
          '预测变量与结果通常在同一份问卷、同一时点收集，共同方法偏差会抬高所观察到的关系。'),
      ],
      temporal=[
        P('The model assumes adoption is voluntary and discrete: a person decides whether to use a bounded system. Much current technology arrives as a mandated platform, an embedded feature, or a default that requires action to avoid - conditions under which an intention model has little to predict.',
          '模型假定采纳是自愿且离散的：个体决定是否使用一个边界清晰的系统。而当下大量技术是被强制部署的平台、嵌入式功能，或需主动规避的默认项——在这些条件下，意向模型几乎无从预测。'),
        P('It was written when the salient risk of a system was that it would be ignored. For algorithmic management, monitoring, and automated decision systems the salient risks are fairness, opacity, and loss of discretion, none of which the two beliefs represent.',
          '它写作之时，系统最突出的风险是"被弃用"。而对算法管理、监控与自动化决策系统而言，突出的风险是公平性、不透明与自主权丧失——这些都不在两个信念的表达范围内。'),
        P('The instrument assumes the user can form a stable belief about what the system does. With systems whose behaviour is probabilistic and changes between versions, the object of the belief is itself unstable.',
          '量表假定用户能对"系统做什么"形成稳定信念。而当系统行为具有概率性、且随版本变化时，信念所指向的对象本身就不稳定。'),
      ],
      today=[
        P('Use it as a control baseline, not as the contribution. If the study is about an AI or monitoring system, the interesting variance is likely in trust, transparency, and perceived fairness rather than in ease of use.',
          '把它当作对照基线，而不是研究贡献本身。若研究对象是 AI 或监控系统，有意思的变异更可能在信任、透明度与公平感上，而不在易用性上。'),
        P('If adoption is mandated, say so and drop the intention chain; measuring intention where there is no choice produces a number without a referent.',
          '若采纳是强制的，就明确说明并放弃意向链条；在没有选择余地的情境下测量意向，得到的是没有指称对象的数字。'),
      ]),
])
