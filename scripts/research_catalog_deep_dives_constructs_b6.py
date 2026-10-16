# -*- coding: utf-8 -*-
"""Deep dives for catalog constructs, batch 6 — clearing zero-coverage disciplines.

Accounting, Entrepreneurship, International Business and Economics had no
construct with a written analysis. These nine cover all four. Where a construct
shares an id-like name with a theory entry (earnings management, entrepreneurial
orientation, opportunity recognition), the treatment here is deliberately about
measurement rather than about the theoretical argument, which lives on the
theory record.

Schema helpers live in ``research_catalog_deep_dives``.
"""

from research_catalog_deep_dives import D, Debate, P, Pos

CONSTRUCT_DIVES_B6 = dict([

    # ------------------------------------------------ financial reporting quality
    D('financial-reporting-quality',
      era='Formalized alongside the earnings-quality literature from the 1990s; measurement never converged.',
      era_zh='1990 年代起与盈余质量文献同步形式化，其测量始终未能收敛。',
      situation=[
        P('Accounting research needed to say whether a set of statements is informative. Compliance with standards was the only observable criterion and does not distinguish a faithful report from a technically compliant but misleading one.',
          '会计研究需要判断一套报表是否具有信息含量。合规是唯一可观察的标准，却无法区分忠实的报告与"技术上合规但具误导性"的报告。'),
        P('The construct was introduced to name what standards are trying to produce, which is a report that faithfully represents the underlying economics.',
          '该构念被提出，用以命名准则试图产出的东西：忠实反映底层经济实质的报告。'),
      ],
      argument=[
        P('Quality has two components that pull apart: relevance, meaning the report contains information useful for a decision, and representational faithfulness, meaning it corresponds to what actually happened.',
          '质量包含两个相互拉扯的成分：相关性，即报告含有对决策有用的信息；以及如实反映，即它与实际发生的情况相符。'),
        P('Because faithfulness is unobservable, the literature measures quality by proxies for its absence — abnormal accruals, restatements, low accrual persistence, or delayed loss recognition.',
          '由于如实性不可观察，文献转而用"缺乏质量"的代理变量来测量：异常应计、财务重述、应计持续性低，或损失确认延迟。'),
        P('That inversion is the central methodological fact about this construct: nearly every empirical claim about reporting quality is a claim about an estimated residual.',
          '这一反转是该构念最核心的方法论事实：几乎所有关于报告质量的经验主张，实际上都是关于一个估计残差的主张。'),
      ],
      development=[
        P('Accrual models were refined repeatedly — cross-sectional estimation, performance matching, cash-flow terms — each addressing a known bias in the previous specification.',
          '应计模型被反复改进——横截面估计、绩效配对、加入现金流项——每一次都针对上一设定中已知的偏误。'),
      ],
      debates=[
        Debate('Do accrual models measure quality or firm characteristics?', '应计模型测的是质量还是企业特征？',
               [Pos('Measurement position',
                    'After controlling for growth and performance, the residual captures reporting discretion and predicts restatements and enforcement actions.',
                    '在控制增长与绩效后，残差捕捉了报告裁量权，并能预测重述与执法行动。'),
                Pos('Misspecification critique',
                    'The residual absorbs everything the model omits, so firms with unusual but legitimate business models are scored as low quality by construction.',
                    '残差吸收了模型遗漏的一切；因此商业模式特殊但完全正当的企业，在构造上就被评为低质量。')],
               'The critique is widely accepted and the models remain standard, so results depend on which specification is chosen.',
               '该批评被广泛接受，而模型仍是标准做法——因此结论取决于选择了哪个设定。'),
      ],
      theoretical=[
        P('Relevance and faithfulness can conflict: a fair-value estimate may be more decision-relevant and less verifiable, and a single quality score cannot represent that trade-off.',
          '相关性与如实性可能冲突：公允价值估计可能更贴近决策却更难验证；单一质量分数无法表达这一取舍。'),
        P('Quality is defined for a user whose decision problem the construct never specifies, although what counts as relevant depends entirely on that problem.',
          '质量是相对于某个使用者定义的，而该构念从未指明其决策问题——尽管"什么算相关"完全取决于这个问题。'),
      ],
      empirical=[
        P('Abnormal accruals are a residual from an estimated model, so measurement error is guaranteed and its magnitude is unknown.',
          '异常应计是估计模型的残差，因此测量误差必然存在，且其量级未知。'),
        P('Restatements measure detected misreporting, so they conflate reporting behaviour with enforcement intensity and audit scrutiny.',
          '财务重述测量的是"被发现的"错报，因而把报告行为与执法强度、审计关注度混在一起。'),
      ],
      temporal=[
        P('The construct assumes financial statements are the primary information channel. Where investors act on alternative data, disclosures outside the statements, and real-time signals, the quality of the statements explains a smaller share of price formation than the literature assumes.',
          '该构念假定财务报表是首要信息渠道。当投资者依据另类数据、报表之外的披露与实时信号行动时，报表质量对价格形成的解释份额低于文献的假定。'),
        P('Accrual models were built for firms whose assets are physical and whose expenditures capitalize. For firms whose main assets are intangible and expensed as incurred, the accrual process the model estimates is not the process generating the numbers.',
          '应计模型是为"资产为实体、支出可资本化"的企业构建的。对于主要资产为无形、且支出即期费用化的企业，模型所估计的应计过程并非生成数字的那个过程。'),
      ],
      today=[
        P('Name the proxy and the specification, and report whether results survive an alternative accrual model. Different models disagree often enough that a single specification is not evidence.',
          '应说明代理变量与模型设定，并报告结论在替代应计模型下是否成立。不同模型的分歧足够频繁，单一设定不构成证据。'),
        P('For intangible-intensive samples, check that the accrual model is defensible before using its residual as a quality measure.',
          '对无形资产密集的样本，在把残差用作质量指标之前，应先检查应计模型是否站得住。'),
      ]),

    # -------------------------------------------------------- earnings management
    D('earnings-management',
      era='Measured through discretionary-accrual models from the mid-1990s; real-activities measures added from 2006.',
      era_zh='自 1990 年代中期起通过操控性应计模型测量，2006 年起补入真实活动操纵指标。',
      situation=[
        P('Accrual accounting requires judgement, and judgement can be used to convey private information or to obscure it. Distinguishing the two empirically requires a measure of the discretionary portion.',
          '权责发生制会计需要判断，而判断既可用于传递私有信息，也可用于掩盖信息。要在经验上区分二者，就需要对裁量部分加以测量。'),
        P('The construct names that portion, and the literature is largely a history of attempts to estimate it.',
          '该构念命名了这一部分，而相关文献在很大程度上就是估计它的一部尝试史。'),
      ],
      argument=[
        P('Accrual-based management shifts recognition across periods without changing cash flows, and is estimated as the residual after modelling normal accruals from sales growth and asset base.',
          '应计操纵在不改变现金流的前提下跨期调整确认时点，其估计方法是：先用销售增长与资产规模拟合正常应计，再取残差。'),
        P('Real-activities management changes actual operations — cutting discretionary spending, overproducing, offering unusual discounts — and is costly because it destroys value rather than merely relocating recognition.',
          '真实活动操纵改变实际经营——削减酌量性支出、超额生产、提供异常折扣——其代价更高，因为它毁损价值而非仅仅移动确认时点。'),
        P('The two substitute for each other, so a study that measures only accruals will conclude that tighter regulation reduced management when it may have shifted its form.',
          '二者相互替代；因此只测量应计的研究会得出"更严监管减少了操纵"的结论，而实际上可能只是操纵形式发生了转移。'),
      ],
      development=[
        P('Real-activities measures were introduced after evidence that managers preferred them once accrual discretion became more scrutinized.',
          '在有证据显示"应计裁量受到更严审视后管理者转向真实活动"之后，真实活动指标被引入。'),
      ],
      debates=[
        Debate('Is earnings management informative or opportunistic?', '盈余管理是传递信息还是机会主义？',
               [Pos('Signalling position',
                    'Discretion lets managers convey private information about persistent performance that mechanical rules would suppress.',
                    '裁量权使管理者能够传递关于持续性业绩的私有信息，而机械规则会压制这类信息。'),
                Pos('Opportunism position',
                    'Discretion clusters around thresholds — beating forecasts, avoiding losses, meeting covenants — which is the signature of self-interest rather than of information.',
                    '裁量行为聚集于各类临界点——超过预测、避免亏损、满足契约条款——这是自利的特征而非信息传递的特征。')],
               'Both occur, and no accrual proxy separates them, which is why the same residual supports opposite interpretations.',
               '两者都存在，而没有任何应计代理变量能把它们分开——这正是同一残差能支撑相反解读的原因。'),
      ],
      theoretical=[
        P('The construct is defined by intent, which is unobservable, so every measure is a behavioural residual that intent must be read into.',
          '该构念以意图定义，而意图不可观察；因此每个指标都是行为残差，意图只能被读入其中。'),
        P('Normal accruals are defined by a model, which means the boundary between normal and discretionary is a modelling choice rather than an accounting fact.',
          '正常应计由模型定义，这意味着"正常"与"操控"之间的界限是建模选择，而非会计事实。'),
      ],
      empirical=[
        P('Discretionary-accrual models have low power to detect economically meaningful management and are mis-specified for firms with extreme performance.',
          '操控性应计模型在检测具经济意义的操纵上功效很低，且对极端绩效企业存在设定错误。'),
        P('Threshold-based evidence — discontinuities around zero earnings — has been shown to arise partly from scaling and sample selection rather than from manipulation.',
          '基于临界点的证据——零盈余附近的分布断点——已被证明部分源于标准化处理与样本选择，而非操纵。'),
      ],
      temporal=[
        P('The measures assume a periodic reporting cycle in which the decision is which period to place a number in. Where guidance, alternative data, and continuous disclosure already inform expectations, the reported number carries less of the surprise these models attribute to it.',
          '这些指标假定存在定期报告周期，其决策是"把某个数字放进哪一期"。当业绩指引、另类数据与持续披露已经塑造了预期时，报告数字所承载的意外成分低于模型对它的归因。'),
        P('Real-activities measures were calibrated on manufacturing, where overproduction and inventory build are visible in cost of goods sold. For service and platform firms the equivalent levers do not appear in those accounts, so the measure captures less of the behaviour where it now occurs.',
          '真实活动指标是在制造业上校准的，那里的超额生产与库存堆积体现在销货成本中。对服务与平台企业，等价的操纵手段并不出现在这些科目里，因此该指标在当下最常发生的场景中反而捕捉更少。'),
      ],
      today=[
        P('Measure accrual and real-activities management together. Reporting only one leaves substitution as an unaddressed alternative explanation.',
          '应同时测量应计操纵与真实活动操纵。只报告其中一种，会使替代效应成为未被处理的竞争性解释。'),
        P('Do not infer intent from a residual. State that the measure is a behavioural proxy and that informative and opportunistic discretion are not separated by it.',
          '不应从残差推断意图。应说明该指标是行为代理变量，且它并未区分信息型裁量与机会主义裁量。'),
      ]),

    # -------------------------------------------------------------- stock return
    D('stock-return',
      era='The standard outcome variable in finance since the 1960s; its interpretation depends entirely on the benchmark.',
      era_zh='自 1960 年代起是金融研究的标准结果变量；其解读完全取决于基准模型。',
      situation=[
        P('Finance needed an outcome that aggregates all information about a firm value. Accounting numbers arrive late, are subject to discretion, and do not price expectations.',
          '金融研究需要一个能汇总企业价值全部信息的结果变量。会计数字滞后、受裁量影响，且不对预期定价。'),
        P('Returns supply that, but a raw return contains market movement, risk compensation, and firm-specific news, and only the last is usually of interest.',
          '收益率提供了这一点，但原始收益包含市场变动、风险补偿与公司特有消息，而通常只有最后一项是研究关心的。'),
      ],
      argument=[
        P('The realized return decomposes into an expected component, which is compensation for bearing risk, and an unexpected component, which reflects news.',
          '已实现收益可分解为预期部分（承担风险的补偿）与非预期部分（反映消息）。'),
        P('Isolating the second requires a model of the first. Any statement about abnormal return is therefore a joint statement about the event and about the asset-pricing model used to benchmark it.',
          '要分离出后者，就需要一个关于前者的模型。因此任何关于异常收益的陈述，都是关于事件与所用资产定价基准模型的联合陈述。'),
        P('This joint-hypothesis property is not a technicality: it means no empirical result in this area rejects a single proposition.',
          '这一联合假说性质并非技术细节：它意味着该领域没有任何经验结果能单独否定某一个命题。'),
      ],
      development=[
        P('Benchmarks moved from the market model to multi-factor models as anomalies accumulated, and each added factor absorbed effects previously reported as abnormal.',
          '随着异象累积，基准从市场模型演进为多因子模型；每新增一个因子，就吸收掉一部分此前被报告为异常的效应。'),
      ],
      debates=[
        Debate('Do factors capture risk or mispricing?', '因子捕捉的是风险还是错误定价？',
               [Pos('Risk position',
                    'Factor premia are compensation for systematic exposures, so a strategy loading on them earns a return without being a free lunch.',
                    '因子溢价是对系统性暴露的补偿；因此加载于因子的策略获得收益，并非无风险套利。'),
                Pos('Mispricing position',
                    'Many factors were discovered by search, weaken after publication, and correspond to no plausible risk, which points to systematic mispricing.',
                    '许多因子是搜索出来的、在发表后减弱、且对应不上任何可信的风险，这指向系统性错误定价。')],
               'Unresolved by design: the joint-hypothesis problem prevents an empirical test that separates them.',
               '在设计上就无法解决：联合假说问题使得不存在能分离二者的经验检验。'),
      ],
      theoretical=[
        P('Abnormal return is defined relative to a model, so the same event yields different abnormal returns under different benchmarks and the choice is rarely justified.',
          '异常收益是相对于模型定义的；同一事件在不同基准下得到不同的异常收益，而这一选择很少被论证。'),
        P('Returns measure value to marginal shareholders, which is not the same as value created, and the two diverge when wealth is transferred rather than created.',
          '收益率测量的是对边际股东的价值，这不同于所创造的价值；当发生财富转移而非价值创造时，二者背离。'),
      ],
      empirical=[
        P('Long-horizon abnormal returns are highly sensitive to the benchmark and to compounding method, and standard errors from overlapping windows are typically understated.',
          '长期异常收益对基准与复利计算方式高度敏感，且重叠窗口下的标准误通常被低估。'),
        P('Survivorship and delisting biases inflate measured returns because the worst outcomes leave the sample precisely when they are worst.',
          '幸存者偏差与退市偏差抬高了所测收益，因为最差的结果恰在最差的时刻离开样本。'),
      ],
      temporal=[
        P('Event-study methods assume information is impounded over a window measurable in days. Where prices react in milliseconds and information reaches participants unequally by speed of access, a daily window measures the aftermath rather than the reaction.',
          '事件研究法假定信息在以"天"为单位的窗口内被吸收。当价格以毫秒反应、且信息按接入速度不均等地到达参与者时，日度窗口测到的是余波而非反应本身。'),
        P('The benchmark models were estimated on periods when index funds held a small share of the market. Where a large share of ownership is passive and flows are mechanical, factor loadings partly reflect index membership rather than the risk exposures they are read as.',
          '基准模型是在指数基金占市场份额很小的时期估计的。当被动持股占比很大、资金流机械化时，因子载荷部分反映的是指数成分身份，而非人们读出的风险暴露。'),
      ],
      today=[
        P('State the benchmark and report results under at least one alternative. An abnormal return without a named model is not an interpretable quantity.',
          '应说明基准模型并至少报告一个替代设定下的结果。没有指明模型的异常收益不是可解读的量。'),
        P('For long horizons, prefer calendar-time portfolios and report how much of the result depends on the compounding convention.',
          '对长期窗口，应优先使用日历时间组合法，并报告结果在多大程度上依赖于复利处理方式。'),
      ]),

    # ------------------------------------------------- entrepreneurial orientation
    D('entrepreneurial-orientation',
      era='Operationalized as a firm-level scale from 1989; dimensionality debated ever since.',
      era_zh='1989 年起被操作化为企业层面量表，其维度结构此后一直存在争议。',
      situation=[
        P('Entrepreneurship research needed to study established firms, not only new ventures. That required a variable describing how entrepreneurially a firm behaves rather than whether it is young.',
          '创业研究需要研究成熟企业而不只是新创企业。这就要求一个描述"企业行为有多创业"的变量，而非它是否年轻。'),
        P('The construct supplies a firm-level posture measure, which made a large comparative literature possible and also imported a set of measurement problems that persist.',
          '该构念提供了企业层面的姿态测量，使大规模比较研究成为可能，同时也带来了一批延续至今的测量问题。'),
      ],
      argument=[
        P('The posture has three core dimensions — innovativeness, proactiveness, and risk taking — with autonomy and competitive aggressiveness added in the five-dimension version.',
          '这一姿态包含三个核心维度——创新性、先动性与风险承担——五维版本另加自主性与竞争进取性。'),
        P('Whether the dimensions must covary is the defining measurement question. If they are a unidimensional posture, a summed score is appropriate; if they vary independently, summing destroys the information.',
          '各维度是否必须共变，是决定性的测量问题。若它们构成单一维度的姿态，加总分数是恰当的；若各自独立变化，加总就毁掉了信息。'),
        P('Evidence favours independent variation, and most studies nonetheless sum, which means the literature averages over configurations that have different consequences.',
          '证据支持各维度独立变化，而多数研究仍然加总——这意味着文献是在对后果不同的多种组态取平均。'),
      ],
      development=[
        P('Configurational and set-theoretic analyses were introduced specifically to preserve the dimensional differences that a summed scale removes.',
          '组态方法与集合论分析被引入，正是为了保留加总量表所抹去的维度差异。'),
      ],
      debates=[
        Debate('Is the construct formative or reflective?', '该构念是形成性的还是反映性的？',
               [Pos('Reflective practice',
                    'The dimensions are treated as indicators of an underlying posture, which licenses summing and the standard reliability statistics.',
                    '各维度被视为某一潜在姿态的指标，这为加总与标准信度统计提供了依据。'),
                Pos('Formative position',
                    'The dimensions constitute rather than reflect the posture, so internal-consistency statistics are inapplicable and a firm can be high on one and low on another.',
                    '各维度构成而非反映该姿态；因此内部一致性统计不适用，企业可以在某一维度高而在另一维度低。')],
               'The formative reading is better supported and the reflective practice remains dominant, which makes reported reliabilities uninformative.',
               '形成性解读证据更充分，而反映性做法仍占主流——这使得所报告的信度指标缺乏信息量。'),
      ],
      theoretical=[
        P('The construct is close to being defined by its outcomes: firms that innovated and took risks successfully are coded as high on a posture that is then used to explain their success.',
          '该构念几乎是由其结果定义的：成功创新并承担风险的企业被编码为姿态高分，而该分数随后又被用来解释它们的成功。'),
        P('It describes a firm-level posture but is measured by asking individual managers, which assumes a coherence across the organization that is asserted rather than shown.',
          '它描述企业层面的姿态，却通过询问个别管理者来测量——这假定了组织内部的一致性，而该一致性是被断言而非被证明的。'),
      ],
      empirical=[
        P('A single respondent, usually the founder or chief executive, reports both the posture and often the performance, which is the strongest possible form of the same-source problem.',
          '通常由单一受访者（创始人或首席执行官）同时报告姿态与绩效，这是同源问题最严重的形式。'),
        P('Samples are drawn from surviving firms, so risk taking that ended a firm is absent and the estimated relationship with performance is biased upward.',
          '样本取自存活企业，因此导致企业消亡的风险承担缺席，所估计的绩效关系被向上偏倚。'),
      ],
      temporal=[
        P('The scale was developed for firms whose entrepreneurial activity took the form of product launches and market entry decided internally. Where activity happens through partnerships, platform participation, and acquisition of small teams, the items ask about a channel that carries less of the behaviour.',
          '量表是为"创业活动表现为内部决策的产品发布与市场进入"的企业开发的。当活动通过合作、平台参与与收购小团队发生时，题项所询问的渠道承载的行为已经变少。'),
        P('Proactiveness was defined as being first to market in a definable industry. Where category boundaries shift and firms enter markets that did not previously exist, being first is not measurable against a stable comparison set.',
          '先动性被定义为在可界定的产业中率先进入市场。当类别边界移动、企业进入此前并不存在的市场时，"率先"无法对照稳定的比较集来测量。'),
      ],
      today=[
        P('Report the dimensions separately and justify any aggregation. If the theory concerns a configuration, use a method that preserves it.',
          '应分维度报告，并为任何加总提供论证。若理论关注的是组态，就应使用能保留组态的方法。'),
        P('Separate the respondent for posture from the source of performance data, and address survivorship explicitly.',
          '应把姿态的受访者与绩效数据来源分开，并明确处理幸存者偏差。'),
      ]),

    # -------------------------------------------------------- opportunity recognition
    D('opportunity-recognition',
      era='Central to entrepreneurship research from the late 1990s; measurement remains largely retrospective.',
      era_zh='自 1990 年代末起成为创业研究的核心，其测量迄今主要仍是回溯性的。',
      situation=[
        P('Entrepreneurship needed to explain why some people act on possibilities others do not notice. Traits explained little, so attention turned to the cognitive process of noticing.',
          '创业研究需要解释：为什么有些人会对他人未察觉的可能性采取行动。特质解释力很弱，于是注意力转向"察觉"这一认知过程。'),
        P('The construct names that process and made a decade of cognitive entrepreneurship research possible, at the cost of a persistent measurement problem.',
          '该构念命名了这一过程，使十年的创业认知研究成为可能，代价是一个持续存在的测量问题。'),
      ],
      argument=[
        P('Recognition depends on prior knowledge: what a person already knows about markets, customer problems, and how to serve them determines which information registers as an opportunity.',
          '识别依赖于先验知识：一个人对市场、顾客问题及服务方式的既有了解，决定了哪些信息会被记录为机会。'),
        P('Alertness adds a dispositional component — scanning, connecting, and evaluating — that varies across people holding knowledge constant.',
          '警觉性补充了一个倾向性成分——扫描、连接与评估——在知识相同的情况下因人而异。'),
        P('The process is usually decomposed into perceiving a change, discovering a fit between means and a need, and creating a business concept, which are separable stages with different antecedents.',
          '该过程通常被分解为感知变化、发现手段与需求之间的匹配，以及创造商业概念——这些是前因各异、可分离的阶段。'),
      ],
      development=[
        P('The discovery-versus-creation debate reframed the question: opportunities may be found in an existing landscape or brought into being through action.',
          '发现观与创造观之争重新框定了问题：机会可能是在既有格局中被找到，也可能是通过行动被带入存在。'),
      ],
      debates=[
        Debate('Do opportunities exist before they are recognized?', '机会在被识别之前就存在吗？',
               [Pos('Discovery position',
                    'Objective conditions create possibilities that exist whether or not anyone notices, which makes recognition a search problem.',
                    '客观条件创造出无论是否被察觉都存在的可能性，这使识别成为一个搜索问题。'),
                Pos('Creation position',
                    'Opportunities are enacted through action and cannot be observed in advance, which makes the search framing a retrospective illusion.',
                    '机会通过行动被建构，事前无法观察；因此搜索式框定是一种回溯性幻觉。')],
               'Unresolved, and it determines whether the construct can be measured prospectively at all.',
               '未决，且它决定了该构念究竟能否被前瞻性地测量。'),
      ],
      theoretical=[
        P('If opportunities are created rather than found, recognition is not a distinct prior stage and the construct describes a reconstruction of what happened.',
          '如果机会是被创造而非被发现的，那么识别并不是一个独立的前置阶段，该构念描述的只是对已发生之事的重构。'),
        P('Recognized opportunities that were not pursued are invisible, so the construct is almost always observed conditional on action.',
          '被识别却未被追求的机会不可见；因此该构念几乎总是在"已采取行动"的条件下被观察。'),
      ],
      empirical=[
        P('Measurement is retrospective and collected from founders who know the outcome, which produces a coherent narrative in which recognition preceded action.',
          '测量是回溯性的，且来自已知结果的创始人，这产出一段"识别先于行动"的连贯叙事。'),
        P('Successful ventures are oversampled, so the estimated relationship between recognition and outcomes is conditioned on the outcome.',
          '成功创业被过度抽样，因此识别与结果之间的估计关系是以结果为条件的。'),
      ],
      temporal=[
        P('Prior-knowledge accounts assume information asymmetry that comes from experience and personal networks. Where market information is broadly searchable and demand can be tested cheaply, the asymmetry that made recognition rare has narrowed and the advantage shifts toward speed of validation.',
          '先验知识解释假定信息不对称来自经验与个人网络。当市场信息可被广泛搜索、需求可以低成本测试时，使识别变得稀缺的那种不对称已经收窄，优势转向验证速度。'),
        P('It was theorized when acting on an opportunity required assembling resources in advance. Where products can be launched and withdrawn quickly, recognition and testing are no longer separable stages, which is the sequence the construct assumes.',
          '它成形于"抓住机会需要预先集结资源"的时期。当产品可以快速上线与撤回时，识别与检验不再是可分离的阶段——而这正是该构念所假定的次序。'),
      ],
      today=[
        P('Collect prospective data where possible — from nascent entrepreneurs before outcomes are known — rather than retrospective accounts from founders of surviving firms.',
          '应尽可能收集前瞻性数据——在结果已知之前从初创阶段创业者处收集——而非从存活企业创始人处获取回溯叙述。'),
        P('Say which stage is being measured. Perceiving, evaluating, and concept formation are different processes and combining them yields an uninterpretable score.',
          '应说明所测的是哪个阶段。感知、评估与概念形成是不同过程，合并它们只会得到无法解读的分数。'),
      ]),

    # ------------------------------------------------------ new venture performance
    D('new-venture-performance',
      era='The dependent variable of entrepreneurship research since the 1980s; still measured inconsistently.',
      era_zh='自 1980 年代起是创业研究的因变量，至今测量仍不一致。',
      situation=[
        P('New ventures cannot be evaluated with the measures used for established firms. Profitability is often absent by design, and survival alone does not distinguish a growing venture from a stalled one.',
          '新创企业无法用成熟企业的指标来评价。盈利往往在设计上就不存在，而仅凭存活也无法区分成长中的企业与停滞的企业。'),
        P('The construct was introduced to cover the alternatives, and its breadth is both what makes it usable and what makes findings hard to compare.',
          '该构念被提出以涵盖各种替代指标；其宽泛性既使它可用，也使研究结论难以比较。'),
      ],
      argument=[
        P('Performance is multidimensional: survival, growth in revenue or employment, profitability, funding milestones, and exit outcomes are distinct and only loosely correlated.',
          '绩效是多维的：存活、收入或雇佣增长、盈利、融资里程碑与退出结果彼此不同，且只是松散相关。'),
        P('Which dimension is appropriate depends on the venture stage and the theory, and using one where another is implied is the most common specification error in this literature.',
          '哪个维度合适取决于创业阶段与理论；在理论隐含另一维度时使用某一维度，是该文献最常见的设定错误。'),
        P('Growth and profitability can be in tension: a venture pursuing scale deliberately suppresses margin, so scoring it low on profitability measures its strategy rather than its performance.',
          '增长与盈利可能相互冲突：追求规模的企业刻意压低利润率；把它在盈利维度上评为低分，测的是它的战略而非它的绩效。'),
      ],
      development=[
        P('Milestone-based measures — funding rounds, product launch, first revenue — were adopted for early-stage ventures where financial measures do not yet exist.',
          '基于里程碑的指标——融资轮次、产品发布、首笔收入——被用于财务指标尚不存在的早期企业。'),
      ],
      debates=[
        Debate('Is survival a performance measure?', '存活算绩效指标吗？',
               [Pos('Survival position',
                    'Continuing to operate is the minimum evidence a venture is viable and is observable without founder cooperation.',
                    '持续经营是企业可行的最低证据，且无需创始人配合即可观察。'),
                Pos('Exit critique',
                    'Ventures close through acquisition and through founders taking better options, so closure conflates failure with success and with choice.',
                    '企业会因被收购、也会因创始人转向更好的机会而关闭；因此"关闭"把失败、成功与选择混为一谈。')],
               'The critique is well supported, and survival remains the most-used measure because it is the most available.',
               '该批评证据充分，而存活仍是最常用的指标——因为它最容易获得。'),
      ],
      theoretical=[
        P('The construct has no single referent, so two studies both predicting new venture performance may be predicting unrelated outcomes.',
          '该构念没有单一所指；因此两项都声称预测新创企业绩效的研究，可能在预测互不相关的结果。'),
        P('Performance is evaluated against goals that vary — some founders seek growth, others independence or income — and a common scale assumes goals the founder may not hold.',
          '绩效是相对于各不相同的目标来评价的——有人追求增长，有人追求独立或收入——统一量表假定了创始人未必持有的目标。'),
      ],
      empirical=[
        P('Failed ventures leave little record, so samples are drawn from survivors and nearly every estimated relationship is conditioned on survival.',
          '失败企业几乎不留记录，因此样本取自幸存者，几乎所有估计关系都以存活为条件。'),
        P('Self-reported performance from founders is common and correlates imperfectly with verifiable measures, in a direction that favours the founder account.',
          '创始人自评绩效很常见，且与可验证指标只是不完全相关，其偏向有利于创始人的叙述。'),
      ],
      temporal=[
        P('Measures were developed when a venture reaching revenue meant it had built operating capacity. Where infrastructure is rented and scale can be reached without fixed investment, revenue milestones represent a different level of commitment than the measures assume.',
          '这些指标形成于"企业实现收入即意味着已建成运营能力"的时期。当基础设施可租用、无需固定投资即可达到规模时，收入里程碑所代表的投入程度已不同于指标的假定。'),
        P('Funding milestones are widely used as performance, but they measure investor assessment at a point in a funding market whose conditions vary by more than venture quality does.',
          '融资里程碑被广泛用作绩效指标，但它测量的是特定时点上投资者的评估——而融资市场的松紧变化幅度远大于企业质量本身的差异。'),
      ],
      today=[
        P('Choose the dimension from the theory and say so. A composite that mixes survival, growth, and profitability cannot be interpreted.',
          '应依据理论选择维度并明确说明。混合存活、增长与盈利的综合指标无法解读。'),
        P('Address survivorship explicitly, and do not treat funding as performance without controlling for funding-market conditions.',
          '应明确处理幸存者偏差，且在未控制融资市场环境的情况下不要把融资视作绩效。'),
      ]),

    # ------------------------------------------------------- internationalization
    D('internationalization',
      era='Measured since the 1970s; the standard indices predate born-global firms and digital delivery.',
      era_zh='自 1970 年代起被测量；标准指数的形成早于天生全球企业与数字化交付。',
      situation=[
        P('International business needed a variable capturing how far a firm has extended beyond its home market, so that antecedents and performance consequences could be studied comparatively.',
          '国际商务研究需要一个刻画企业在多大程度上超出母国市场的变量，以便对其前因与绩效后果进行比较研究。'),
        P('The measures that emerged encode a specific view of what expansion involves — foreign sales, foreign assets, foreign employment — which was accurate for the firms of that period.',
          '由此形成的指标编码了对"扩张包含什么"的特定看法——海外销售、海外资产、海外雇佣——这在当时的企业身上是准确的。'),
      ],
      argument=[
        P('Internationalization has a degree dimension, how much activity is abroad, and a scope dimension, how many and how distant the countries are. They are not interchangeable.',
          '国际化包含程度维度（海外活动占多少）与范围维度（涉及多少国家、距离多远），二者不可互换。'),
        P('Composite indices average foreign sales, assets, and subsidiaries, on the assumption that these move together, which holds for manufacturing firms committing physical resources.',
          '综合指数对海外销售、资产与子公司数取平均，前提是三者同向变动——这对投入实体资源的制造企业成立。'),
        P('The performance relationship is usually specified as non-linear, with early costs of foreignness followed by benefits and then coordination costs at high degrees.',
          '其绩效关系通常被设定为非线性：早期承担外来者劣势，随后获得收益，程度过高时又出现协调成本。'),
      ],
      development=[
        P('Born-global evidence showed firms internationalizing at founding, which contradicted the staged view the measures were built to describe.',
          '天生全球企业的证据显示企业在创立之初就国际化，这与指标所要描述的阶段论相矛盾。'),
      ],
      debates=[
        Debate('Is the performance relationship S-shaped?', '绩效关系是 S 形的吗？',
               [Pos('Three-stage position',
                    'Costs dominate early, benefits accrue in the middle range, and coordination costs return at high degrees, which fits the accumulated evidence.',
                    '早期成本主导，中段获得收益，程度过高时协调成本回归——这符合累积的证据。'),
                Pos('Artefact critique',
                    'The shape is sensitive to sample, index construction, and the performance measure, and meta-analyses find the effect small and unstable.',
                    '该形状对样本、指数构造与绩效指标高度敏感，元分析发现效应很小且不稳定。')],
               'Contested. The shape is reported often enough that its instability across specifications is the more informative finding.',
               '存在争议。这一形状被报告得足够频繁，以至于"它在不同设定下并不稳定"反而是更有信息量的发现。'),
      ],
      theoretical=[
        P('The construct treats crossing a national border as the meaningful boundary, although for many firms the relevant differences are regulatory or linguistic and do not follow borders.',
          '该构念把跨越国界当作有意义的边界，尽管对许多企业而言，真正相关的差异是监管或语言上的，并不沿国界分布。'),
        P('Degree and scope are combined into one index although a firm deep in one foreign market and a firm shallow in twenty are not comparable.',
          '程度与范围被合并为一个指数，尽管"在一个海外市场深耕"与"在二十个市场浅尝"的企业并不可比。'),
      ],
      empirical=[
        P('Foreign sales are reported by segment under rules that vary by jurisdiction and change over time, so the same firm can show discontinuities that reflect disclosure rather than activity.',
          '海外销售按分部披露，而披露规则因司法辖区而异并随时间变化；因此同一企业可能出现反映披露口径而非实际活动的断点。'),
        P('Tax-driven structures place assets and revenues where activity does not occur, which distorts asset- and sales-based indices in the same direction across firms.',
          '税务驱动的架构把资产与收入放在并无实际活动的地方，这使基于资产与销售的指数在众多企业中朝同一方向失真。'),
      ],
      temporal=[
        P('The measures assume serving a foreign market requires local presence. Where a service is delivered digitally, a firm can have most of its users abroad and almost no foreign assets or employees, and the standard index scores it as barely international.',
          '这些指标假定服务海外市场需要本地存在。当服务以数字方式交付时，企业的多数用户可能在海外，却几乎没有海外资产或雇员——标准指数会把它评为几乎未国际化。'),
        P('The staged model behind the measures assumed learning accumulates through sequential commitment. Firms that reach many markets at founding do not pass through the stages, so their index value does not carry the experiential meaning the construct attaches to it.',
          '指标背后的阶段模型假定学习通过逐步承诺累积。在创立之初就进入多个市场的企业并不经历这些阶段；因此其指数值不承载该构念所赋予的经验含义。'),
      ],
      today=[
        P('Report degree and scope separately, and state which one the theory concerns, because a firm deep in one market and a firm present in twenty are not comparable.',
          '应分别报告程度与范围，并说明理论关注的是哪一个——在一个市场深耕的企业与出现在二十个市场的企业并不可比。'),
        P('For digital and service firms, use a measure based on where customers are rather than where assets are, and say why the standard index was not used.',
          '对数字与服务型企业，应使用基于"顾客在哪里"而非"资产在哪里"的指标，并说明为何未采用标准指数。'),
      ]),

    # ---------------------------------------------------- institutional distance
    D('institutional-distance',
      era='Formalized around 2002 following the institutional turn in international business.',
      era_zh='在国际商务的制度转向之后于 2002 年前后形式化。',
      situation=[
        P('Cultural distance measures could not explain why firms struggled in countries culturally similar to home but institutionally different, such as in property rights or regulatory enforcement.',
          '文化距离指标无法解释：为什么企业在文化相近但制度不同的国家（如产权或监管执行方面）会陷入困难。'),
        P('The construct separated the institutional environment from the cultural one, which was necessary because the two do not covary reliably.',
          '该构念把制度环境与文化环境分开——这是必要的，因为二者并不稳定共变。'),
      ],
      argument=[
        P('Distance is measured across regulative, normative, and cognitive pillars, which correspond to rules, professional norms, and shared understandings.',
          '距离在管制性、规范性与认知性三大支柱上测量，分别对应规则、职业规范与共享认知。'),
        P('Greater distance raises the cost of transferring practices and of establishing legitimacy, which is the mechanism behind the liability of foreignness.',
          '距离越大，实践迁移与建立合法性的成本越高——这正是外来者劣势背后的机制。'),
        P('The three pillars have different consequences: regulative distance raises compliance cost, while cognitive distance affects whether a practice is understood at all.',
          '三个支柱后果不同：管制距离抬高合规成本，而认知距离影响的是某项实践是否能被理解。'),
      ],
      development=[
        P('Direction was added: moving from a weaker to a stronger institutional environment is not equivalent to the reverse, which symmetric distance measures cannot represent.',
          '方向性被补入：从较弱制度环境进入较强环境，与反向并不等价——对称的距离指标无法表达这一点。'),
      ],
      debates=[
        Debate('Should distance be symmetric?', '距离应当是对称的吗？',
               [Pos('Symmetric practice',
                    'A difference index is simple, comparable across pairs, and captures the transfer cost that arises in either direction.',
                    '差异指数简洁、可跨国家对比，并捕捉了两个方向上都会产生的迁移成本。'),
                Pos('Asymmetric position',
                    'Entering a stronger regime imposes compliance cost while entering a weaker one imposes governance risk, and these are different problems.',
                    '进入更强的制度体系带来合规成本，进入更弱的体系带来治理风险，二者是不同的问题。')],
               'The asymmetric reading is better supported and symmetric indices are still standard.',
               '非对称解读证据更充分，而对称指数仍是标准做法。'),
      ],
      theoretical=[
        P('Distance is computed between country averages, which assumes institutional environments are homogeneous within a country and ignores subnational variation that is often larger.',
          '距离按国家均值计算，这假定一国内部制度环境同质，忽略了往往更大的次国家层面差异。'),
        P('The construct treats distance as a cost, although institutional difference can also be a reason to enter — arbitrage across regimes is a strategy, not only a friction.',
          '该构念把距离视为成本，然而制度差异也可能是进入的理由——跨体制套利是一种策略，而不仅是摩擦。'),
      ],
      empirical=[
        P('Composite indices are built from governance indicators that are themselves partly perception surveys of business elites, so the measure embeds the views of a particular respondent group.',
          '综合指数由治理指标构建，而这些指标本身部分是对商界精英的感知调查；因此该指标嵌入了特定受访群体的看法。'),
        P('Distance measures are highly collinear with development level, so effects attributed to institutional difference may reflect income and market size.',
          '距离指标与发展水平高度共线；因此被归因于制度差异的效应，可能反映的是收入与市场规模。'),
      ],
      temporal=[
        P('The pillars were operationalized when regulation was territorial. Where rules apply extraterritorially — data protection, sanctions, platform regulation — a firm faces the regulative environment of markets it has not entered, and a bilateral distance measure does not represent that.',
          '三大支柱的操作化发生在监管属地化的时期。当规则具有域外效力时——数据保护、制裁、平台监管——企业会面对其并未进入的市场的管制环境，而双边距离指标无法表达这一点。'),
        P('Institutional environments have been changing faster than the indices are updated, so a distance computed from a fixed base year attributes to institutions a difference that may have closed or widened since.',
          '制度环境的变化速度快于指数的更新；因此以固定基年计算的距离，会把此后可能已收窄或扩大的差异归因于制度。'),
      ],
      today=[
        P('Report the pillars separately, state the direction, and check collinearity with development indicators before attributing an effect to institutions.',
          '应分支柱报告、说明方向，并在把效应归因于制度之前检查与发展水平指标的共线性。'),
        P('Use time-varying institutional data where the study period spans institutional change rather than a fixed base year.',
          '当研究期跨越制度变迁时，应使用时变制度数据而非固定基年。'),
      ]),

    # -------------------------------------------------------- cultural distance
    D('cultural-distance',
      era='Operationalized as a composite index in 1988; criticized comprehensively in 2001 and still widely used.',
      era_zh='1988 年被操作化为综合指数，2001 年遭到系统性批评，至今仍被广泛使用。',
      situation=[
        P('International business needed a single number for how different two countries are, so that entry mode, subsidiary performance, and expatriate outcomes could be modelled across many country pairs.',
          '国际商务研究需要一个刻画两国差异程度的单一数字，以便在众多国家配对上对进入模式、子公司绩效与外派结果建模。'),
        P('A composite of value-dimension differences supplied that, and its convenience made it one of the most used constructs in the field.',
          '基于价值维度差异的综合指数提供了这一点，其便利性使它成为该领域使用最多的构念之一。'),
      ],
      argument=[
        P('The index aggregates differences across national value dimensions into one Euclidean-style distance between country means.',
          '该指数把各国在价值维度上的差异汇总为国家均值之间的欧氏式距离。'),
        P('Greater distance is argued to raise the cost of transferring practices, coordinating across units, and interpreting local behaviour, which predicts entry mode and subsidiary outcomes.',
          '距离越大，实践迁移、跨单元协调与解读本地行为的成本越高——由此预测进入模式与子公司结果。'),
      ],
      development=[
        P('Alternative frameworks with different dimensions were developed, and results change depending on which underlying value survey the index is computed from.',
          '采用不同维度的替代框架相继出现；结论会随指数所依据的价值观调查而改变。'),
      ],
      debates=[
        Debate('Is the index valid?', '该指数有效吗？',
               [Pos('Continued-use position',
                    'It predicts entry mode and performance consistently enough across studies to be informative, and no better single measure has replaced it.',
                    '它在众多研究中对进入模式与绩效的预测足够稳定，具有信息量，且尚无更好的单一指标取代它。'),
                Pos('Illusion critique',
                    'The index rests on assumptions of symmetry, stability, linearity, and within-country homogeneity that are each demonstrably false.',
                    '该指数建立在对称性、稳定性、线性与国内同质性的假定之上，而每一项都可被证明为假。')],
               'The critique has been accepted in principle for two decades and the index remains in routine use, which is itself the notable fact.',
               '这一批评在原则上已被接受二十年，而指数仍在常规使用——这本身就是值得注意的事实。'),
      ],
      theoretical=[
        P('Distance is symmetric by construction, so the index cannot distinguish a firm from a high-power-distance country entering a low one from the reverse, although the adjustment problems differ.',
          '距离在构造上是对称的；因此该指数无法区分"高权力距离国家的企业进入低权力距离国家"与其反向情形，尽管二者的适应问题并不相同。'),
        P('Aggregating dimensions assumes they are equally important and substitutable, so a large difference on one dimension is treated as equivalent to small differences on several.',
          '维度加总假定各维度同等重要且可替代；因此某一维度上的巨大差异被视同为多个维度上的细小差异。'),
      ],
      empirical=[
        P('The underlying value scores come from surveys conducted decades ago in specific occupational populations, and they are applied to countries whose composition has changed substantially.',
          '底层价值分数来自数十年前在特定职业群体中开展的调查，却被套用于人口构成已显著变化的国家。'),
        P('Within-country variation exceeds between-country variation on several dimensions, so a national mean is a poor description of any individual encounter.',
          '在若干维度上，国内差异超过国家间差异；因此国家均值对任何具体接触而言都是糟糕的描述。'),
      ],
      temporal=[
        P('The value data were collected in a period of limited cross-border media and mobility. Applying scores from that period to populations that have since had sustained exposure to one another attributes to culture a distance that may have narrowed.',
          '价值观数据采集于跨境媒介与流动有限的时期。把当时的分数套用于此后长期彼此接触的人群，会把可能已经收窄的距离归因于文化。'),
        P('The construct assumes an employee is embedded in one national culture. Where teams are distributed and members work across several national contexts continuously, assigning a person a single national score misdescribes the exposure the theory is about.',
          '该构念假定雇员嵌入于单一国家文化。当团队分布式、成员持续跨多个国家情境工作时，给个体赋予单一国家分数，错误描述了理论所关注的那种接触。'),
      ],
      today=[
        P('Prefer dimension-level differences over the composite, and report direction rather than absolute distance.',
          '应优先使用维度层面的差异而非综合指数，并报告方向而非绝对距离。'),
        P('If the composite is used, state the value survey and year and acknowledge that within-country variation is not represented.',
          '若使用综合指数，应说明所依据的价值观调查与年份，并承认国内差异未被表达。'),
      ]),
])
