# -*- coding: utf-8 -*-
"""Deep dives for catalog methods, batch 2.

Panel and event-based designs, evidence synthesis, and the two qualitative
methods most often named in the corpus. Several of these share the staggered
timing problem documented on the difference-in-differences page, which is noted
where it applies rather than repeated in full.

Schema helpers live in ``research_catalog_deep_dives``.
"""

from research_catalog_deep_dives import D, Debate, P, Pos

METHOD_DIVES_B2 = dict([

    # ----------------------------------------------------------- fixed effects
    D('fixed-effects',
      era='Standard in econometrics for decades; its use as a general confounding remedy in management research spread from the 1990s.',
      era_zh='在计量经济学中长期作为标准工具，1990 年代起作为"通用去混淆手段"在管理研究中扩散。',
      situation=[
        P('Panel data offered something cross-sections could not: the same unit observed repeatedly, so that stable differences between units could in principle be removed rather than controlled for one at a time.',
          '面板数据提供了横截面所没有的东西：同一单位被重复观测，因而单位间的稳定差异原则上可以被整体消去，而不必逐个控制。'),
        P('The appeal was that it removes every time-invariant confounder at once, including the ones the researcher never thought of and could not measure.',
          '其吸引力在于一次性消去所有不随时间变化的混淆因素，包括研究者从未想到、也无法测量的那些。'),
      ],
      argument=[
        P('The estimator subtracts each unit own mean from its observations, so only within-unit deviation remains. Anything constant within a unit — founding conditions, culture, location, unmeasured managerial quality — drops out of the equation.',
          '该估计量从每个单位的观测中减去其自身均值，只留下单位内部的偏离。任何在单位内恒定的因素——创立条件、文化、区位、不可测的管理质量——都从方程中消失。'),
        P('That is also the cost. The coefficient is identified only from units whose regressor actually changes, and time-invariant variables cannot be estimated at all because they were differenced away.',
          '这同时也是代价。系数只由"自变量确实发生变化"的单位识别，而不随时间变化的变量根本无法估计，因为它们已被差分掉。'),
      ],
      development=[
        P('High-dimensional absorption made it practical to include unit, time, and interacted effects simultaneously, which increased its use and also made it easier to absorb the variation the study needed.',
          '高维吸收使同时纳入单位、时间及其交互效应变得可行，这既扩大了它的使用，也让研究所需的变异更容易被一并吸收掉。'),
      ],
      debates=[
        Debate('Does adding fixed effects make a design causal?', '加入固定效应就使设计具有因果性吗？',
               [Pos('Common practice',
                    'Unit and year effects are added routinely and the resulting estimate is discussed causally.',
                    '例行加入单位与年度效应，并对所得估计作因果讨论。'),
                Pos('Design-based position',
                    'They remove time-invariant confounding only; any time-varying confounder correlated with the regressor survives, and most interesting confounders vary over time.',
                    '它们只消去不随时间变化的混淆；与自变量相关且随时间变化的混淆依然存在，而多数值得关注的混淆恰恰随时间变化。')],
               'Settled in methods writing, widely ignored in application. Fixed effects are a control strategy, not an identification strategy.',
               '方法学写作中已有定论，应用中普遍被忽视。固定效应是控制策略，不是识别策略。'),
      ],
      theoretical=[
        P('The estimand is a within-unit effect. It answers what happens when a unit changes, not what would happen if a different unit had a different value, and those are different questions.',
          '其估计目标是单位内效应。它回答的是"某单位发生变化时会怎样"，而非"若另一单位取不同值会怎样"——这是两个不同问题。'),
        P('Absorbing a fixed effect does not show the absorbed characteristic is unimportant; it shows the design has chosen not to learn about it.',
          '吸收掉某个固定效应，并不表明被吸收的特征不重要，只表明设计选择了不去了解它。'),
      ],
      empirical=[
        P('Where the regressor barely moves within units, fixed effects amplify measurement error and inflate standard errors, and the resulting null is often reported as evidence of no effect.',
          '当自变量在单位内几乎不变动时，固定效应会放大测量误差、抬高标准误，而由此得到的零结果常被报告为"无效应"的证据。'),
        P('Two-way fixed effects with staggered treatment timing is biased under heterogeneous effects for the same reason documented on the difference-in-differences page, and the problem applies wherever this specification is used to estimate a treatment effect.',
          '在错时处理下，双向固定效应在效应异质时有偏，原因与双重差分页面所记录的相同；只要用该写法估计处理效应，问题就同样存在。'),
      ],
      temporal=[
        P('The convention of adding unit and year effects as a default was established when the alternative was pooled OLS with a handful of controls, and it was a genuine improvement. Reviewer expectations have since moved to requiring an identification argument, and fixed effects alone no longer carry a causal claim.',
          '"默认加入单位与年度效应"的惯例确立于替代方案只是"加几个控制变量的混合 OLS"之时，当时确是实质改进。此后评审期待已转向要求识别论证，仅凭固定效应不再足以支撑因果主张。'),
        P('Results published before the staggered-timing literature that used two-way fixed effects on differently timed treatments should be read with that bias in mind, independent of how the paper described its design.',
          '在错时处理文献出现之前发表、且对不同时点的处理使用双向固定效应的结果，应带着该偏误来读，无论论文如何描述其设计。'),
      ],
      today=[
        P('Report how much of the regressor variation is within units. If the answer is very little, the specification is discarding the information the study depends on.',
          '应报告自变量的变异有多少来自单位内部。若答案是很少，该设定正在丢弃研究所依赖的信息。'),
        P('Say what the fixed effects rule out and what they do not. Naming the remaining time-varying threats is the argument; the regression is not.',
          '应说明固定效应排除了什么、没有排除什么。指认剩余的时变威胁才是论证，回归本身不是。'),
      ]),

    # -------------------------------------------------------------- panel data
    D('panel-data',
      era='Established as a distinct analytic tradition from the 1960s; attrition and dynamic-panel problems documented through the 1980s and 1990s.',
      era_zh='1960 年代起成为独立的分析传统，样本流失与动态面板问题在 1980—1990 年代被系统记录。',
      situation=[
        P('Cross-sections cannot separate differences between units from changes within them, and time series on one unit cannot separate the unit from the period. Panels observe both dimensions and can, in principle, tell them apart.',
          '横截面无法区分单位间差异与单位内变化，单一单位的时间序列又无法区分单位与时期。面板同时观测两个维度，原则上可以把它们分开。'),
        P('That is also what makes panels demanding: the design has to state which dimension the theoretical claim is about before an estimator can be chosen.',
          '这也正是面板数据要求高的地方：在选择估计量之前，设计必须先说明理论主张针对的是哪个维度。'),
      ],
      argument=[
        P('The central decomposition is between-unit versus within-unit variation. A theory about why some firms differ from others is a between claim; a theory about what happens when a firm changes is a within claim, and the same dataset answers them with different estimators.',
          '核心分解是单位间变异与单位内变异。"为何某些企业不同于其他企业"是单位间主张；"某企业发生变化时会怎样"是单位内主张——同一数据集需用不同估计量来回答。'),
        P('Because observations from the same unit are not independent, inference must account for that dependence; clustering at the unit level is the minimum, and serial correlation within units frequently requires more.',
          '由于同一单位的观测不独立，推断必须处理这种依赖；按单位聚类是最低要求，而单位内的序列相关往往还需更多处理。'),
      ],
      development=[
        P('Dynamic panel estimators were developed for models with a lagged dependent variable, where the within transformation itself induces correlation with the error and ordinary fixed effects are biased.',
          '为含滞后因变量的模型发展出动态面板估计量：在这类模型中，组内变换本身会诱发与误差项的相关，普通固定效应因而有偏。'),
      ],
      debates=[
        Debate('Is unbalanced attrition ignorable?', '不平衡的样本流失可以忽略吗？',
               [Pos('Common practice',
                    'Unbalanced panels are used as given, with attrition mentioned as a limitation and no adjustment made.',
                    '直接使用非平衡面板，在局限部分提一句流失，不作任何调整。'),
                Pos('Selection position',
                    'Units leave for reasons related to the outcome — firms fail, employees quit — so attrition is informative and ignoring it biases the estimate toward survivors.',
                    '单位退出的原因与结果相关——企业倒闭、员工离职——因此流失本身含有信息，忽略它会使估计偏向存活者。')],
               'The critique is accepted in principle; attrition analysis remains uncommon in applied management panels.',
               '该批评在原则上已被接受，但流失分析在应用型管理面板中仍不常见。'),
      ],
      theoretical=[
        P('A panel does not by itself establish causal direction. Observing both variables repeatedly narrows some alternatives but leaves reverse causation and common time-varying causes intact.',
          '面板本身并不确立因果方向。重复观测两个变量能排除部分替代解释，却无法排除反向因果与共同的时变原因。'),
        P('The choice between fixed and random effects is a theoretical claim about whether unit effects are correlated with the regressors, not a statistic to be read off a test.',
          '固定效应与随机效应之间的选择，是关于"单位效应是否与自变量相关"的理论主张，而不是可从检验结果直接读出的统计量。'),
      ],
      empirical=[
        P('Panels are frequently assembled from sources with different coverage over time, so an apparent trend can be an artefact of which units entered the data when.',
          '面板常由不同时期覆盖范围不同的来源拼装而成，因此表面上的趋势可能只是"哪些单位在何时进入数据"的假象。'),
        P('Serial correlation is routinely under-corrected, which understates standard errors substantially in panels with many periods.',
          '序列相关常被校正不足，在期数较多的面板中会大幅低估标准误。'),
      ],
      temporal=[
        P('Standard practice was established with panels of tens of periods on hundreds of firms drawn from annual filings. High-frequency operational panels from platform and sensor data have different properties — far more periods, irregular spacing, and attrition that is itself an outcome — and the conventional estimators and standard-error corrections do not transfer unexamined.',
          '标准做法确立于"数百家企业、数十期、来自年报"的面板。来自平台与传感器的高频运营面板性质不同——期数多得多、间隔不规则、且流失本身就是一个结果——常规估计量与标准误校正无法未经检视地迁移。'),
        P('Clustering guidance has tightened. Analyses published when clustering was optional often report standard errors that would not pass review now, so their precision should not be taken at face value.',
          '聚类指引已收紧。在"聚类可选"时期发表的分析所报告的标准误，如今往往通不过评审，其精度不应按表面价值接受。'),
      ],
      today=[
        P('State whether the claim is within or between before estimating, and choose the estimator to match rather than defaulting to fixed effects.',
          '应在估计之前说明主张是单位内还是单位间的，并据此选择估计量，而不是默认使用固定效应。'),
        P('Report the panel structure: units, periods, balance, and who left when. An attrition table is cheap and it is the main thing a reader cannot reconstruct.',
          '应报告面板结构：单位数、期数、平衡性，以及谁在何时退出。流失表成本很低，而它恰恰是读者无法自行重建的关键信息。'),
      ]),

    # ------------------------------------------------------------- event study
    D('event-study',
      era='Established in finance in 1969; adapted to management and strategy research from the 1980s.',
      era_zh='1969 年在金融学中确立，1980 年代起被引入管理与战略研究。',
      situation=[
        P('Researchers wanted to know whether a corporate action created value, but accounting outcomes appear slowly and are contaminated by everything else the firm does in the same period.',
          '研究者想知道某项公司行为是否创造了价值，但会计结果显现缓慢，且被同期企业所做的其他一切所污染。'),
        P('If markets incorporate information quickly, the price reaction in a short window around the announcement isolates the market assessment of that specific action, which is a much cleaner outcome than annual performance.',
          '若市场能快速吸收信息，公告前后短窗口内的价格反应就分离出市场对该特定行为的评估——这是比年度绩效干净得多的结果变量。'),
      ],
      argument=[
        P('A model of normal returns is estimated over an earlier window, then abnormal return is the difference between actual and predicted return during the event window, cumulated across days.',
          '先在较早的窗口估计正常收益模型，事件窗口内实际收益与预测收益之差即为异常收益，再在窗口内逐日累积。'),
        P('The whole design rests on the event being unanticipated and on the window being short enough that nothing else material happens in it. Both are design decisions made before estimation, and neither is testable afterwards.',
          '整个设计依赖两点：事件未被预期，且窗口短到其间没有其他重大事件。二者都是估计之前的设计决策，事后都无法检验。'),
      ],
      development=[
        P('The same relative-time logic was carried into panel settings as the event-study specification used alongside difference-in-differences, where coefficients on leads and lags trace the dynamics of a treatment rather than a price reaction.',
          '同样的相对时间逻辑被带入面板情境，成为与双重差分并用的事件研究设定：领先与滞后项的系数刻画处理效应的动态，而非价格反应。'),
      ],
      debates=[
        Debate('How long should the event window be?', '事件窗口应当多长？',
               [Pos('Short-window position',
                    'Only a window of a few days is defensible; over longer horizons the normal-return model is unreliable and confounding events accumulate.',
                    '只有数日的窗口是可辩护的；窗口越长，正常收益模型越不可靠，混淆事件也不断累积。'),
                Pos('Long-window position',
                    'Effects that take time to be understood by the market are missed entirely by short windows, so some questions require longer horizons.',
                    '市场需要时间才能理解的效应会被短窗口完全错过，因此某些问题需要更长的时间跨度。')],
               'Largely settled in favour of short windows for inference, with long-horizon results treated as suggestive rather than confirmatory.',
               '基本判定为：推断应使用短窗口，长期结果只作提示性证据而非确证。'),
      ],
      theoretical=[
        P('The estimate is the market revision of expectations, not the realized value of the action. A reaction of zero means the market already expected it, which is not the same as the action having no effect.',
          '估计值是市场对预期的修正，而非该行为已实现的价值。反应为零意味着市场早已预期到，这与"该行为没有效果"并不相同。'),
        P('It requires an efficient enough market and a security whose price responds. The design does not transfer to private firms or to outcomes with no traded claim.',
          '它要求市场足够有效、且证券价格会作出反应。该设计无法迁移到私营企业，或没有可交易求偿权的结果。'),
      ],
      empirical=[
        P('Event dates are frequently taken from databases that record the reporting date rather than the first public disclosure, which shifts the window off the actual information release.',
          '事件日期常取自记录"报道日"而非"首次公开披露日"的数据库，这会使窗口偏离真正的信息释放时点。'),
        P('Clustering in calendar time — many firms experiencing the same event on the same day — violates the independence assumption and inflates significance unless explicitly handled.',
          '日历时间上的聚集——多家企业在同一天经历同一事件——违反独立性假定；若不显式处理，会抬高显著性。'),
      ],
      temporal=[
        P('The method assumes information reaches the market through discrete, datable announcements. Where material information leaks through continuous disclosure, social media, and alternative data, the clean pre-event baseline the design depends on is progressively harder to establish.',
          '该方法假定信息通过离散、可定日期的公告到达市场。当重要信息经由持续披露、社交媒体与另类数据泄露时，设计所依赖的干净事前基线越来越难以建立。'),
        P('It was developed when trading reacted over hours or days. Where reaction is substantially complete within minutes, daily-return windows may straddle both the reaction and subsequent unrelated noise.',
          '它发展于交易反应以小时或天计的时期。当反应在数分钟内基本完成时，日频收益窗口可能同时涵盖反应本身与其后不相关的噪声。'),
      ],
      today=[
        P('Fix the event date from the first public disclosure and justify the window before looking at returns. Window choice after seeing results is the main way this design is abused.',
          '应以首次公开披露确定事件日，并在查看收益之前论证窗口长度。看到结果后再选窗口，是该设计最主要的滥用方式。'),
        P('Handle calendar clustering explicitly when events concentrate in time, and report the normal-return model rather than only the abnormal returns.',
          '当事件在时间上集中时应显式处理日历聚集，并报告正常收益模型本身，而不只是异常收益。'),
      ]),

    # ------------------------------------------------------------ meta-analysis
    D('meta-analysis',
      era='Named and formalized in 1976; reporting standards and bias-correction methods reshaped substantially from the 2010s.',
      era_zh='1976 年命名并形式化，报告标准与偏倚校正方法自 2010 年代起被大幅重塑。',
      situation=[
        P('Literatures accumulated studies with conflicting results, and narrative reviews resolved the conflict by the reviewer judgement, which was neither reproducible nor auditable.',
          '文献不断累积结果相互冲突的研究，而叙述性综述依靠综述者的判断来化解冲突，既不可复现也不可审计。'),
        P('Meta-analysis replaced that judgement with a stated procedure: define inclusion rules in advance, convert results to a common metric, and let the pooled estimate and its heterogeneity be computed rather than asserted.',
          '元分析以明确程序取代这种判断：事先界定纳入规则，把结果转换为共同度量，让合并估计及其异质性被计算出来而非被断言。'),
      ],
      argument=[
        P('Each study contributes an effect size weighted by its precision, so larger and better-estimated studies count more. The output is a pooled effect and, more importantly, a quantified account of how much studies disagree.',
          '每项研究贡献一个按其精度加权的效应量，因而样本更大、估计更精确的研究权重更高。产出是合并效应，更重要的是对"研究之间分歧有多大"的量化刻画。'),
        P('Heterogeneity is the substantive finding as often as the pooled mean. If studies disagree beyond sampling error, the interesting question is which study characteristics explain the disagreement.',
          '异质性与合并均值同样常常是实质性发现。若研究间的分歧超出抽样误差，值得追问的是哪些研究特征解释了这些分歧。'),
      ],
      development=[
        P('Random-effects models became standard as it was accepted that studies estimate related but non-identical effects, and dependence-aware models were developed for the common case of multiple effect sizes per sample.',
          '随着"各研究估计的是相关但不同的效应"被接受，随机效应模型成为标准；针对"同一样本多个效应量"这一常见情形，也发展出处理依赖关系的模型。'),
      ],
      debates=[
        Debate('Can publication bias be corrected?', '发表偏倚能被校正吗？',
               [Pos('Correction position',
                    'Funnel asymmetry tests, trim-and-fill, and selection models estimate and adjust for the missing studies.',
                    '漏斗图不对称检验、剪补法与选择模型可以估计并校正缺失研究。'),
                Pos('Skeptical position',
                    'These methods assume a specific mechanism for what is missing and perform poorly when heterogeneity is high or the mechanism differs, so a corrected estimate can be worse than the uncorrected one.',
                    '这些方法对"缺失什么"假定了特定机制；当异质性高或机制不同时表现很差，校正后的估计可能比未校正的更糟。')],
               'Open. Current guidance is to report several methods and treat agreement, not any single correction, as the evidence.',
               '未决。当前指引是报告多种方法，并把它们之间的一致性（而非任一单独校正结果）视为证据。'),
      ],
      theoretical=[
        P('Pooling requires that the studies estimate the same underlying quantity. Combining results that operationalize the construct differently produces a precise number without a clear referent.',
          '合并的前提是各研究估计同一个底层量。把构念操作化方式不同的结果合并，会得到一个精确却没有明确指称的数字。'),
        P('A meta-analysis inherits the designs it summarizes. Pooling many cross-sectional studies gives a precise estimate of an association, not evidence of causation.',
          '元分析继承它所汇总的研究设计。合并大量横截面研究，得到的是关联的精确估计，而非因果证据。'),
      ],
      empirical=[
        P('Multiple effect sizes drawn from one sample are frequently treated as independent, which understates standard errors and overstates the precision of the pooled estimate.',
          '同一样本提取的多个效应量常被当作独立处理，这会低估标准误并高估合并估计的精度。'),
        P('Coding decisions — which studies qualify, how a construct is matched, how moderators are classified — are consequential and are often documented too thinly to be reproduced.',
          '编码决策——哪些研究合格、构念如何匹配、调节变量如何归类——影响重大，却常常记录过于简略而无法复现。'),
      ],
      temporal=[
        P('Meta-analyses of literatures produced before preregistration are summarizing a body of work generated under flexible analysis and selective reporting. The pooled estimate is then a precise summary of a biased sample, and precision should not be mistaken for accuracy.',
          '对预注册之前所产生文献的元分析，汇总的是在弹性分析与选择性报告下生成的研究体。合并估计因而是对一个有偏样本的精确总结，不应把精确当作准确。'),
        P('Standards moved from reporting a pooled effect to requiring a preregistered protocol, a search log, inter-coder reliability, and multiple bias assessments. Older meta-analyses meeting the standards of their time will not meet current ones.',
          '标准已从"报告合并效应"转向要求预注册方案、检索日志、编码者间信度与多重偏倚评估。符合当年标准的旧元分析，达不到当前标准。'),
      ],
      today=[
        P('Preregister the protocol and publish the coding sheet. The credibility of a meta-analysis rests on decisions made before the effect sizes were seen.',
          '应预注册方案并公开编码表。元分析的可信度取决于"在看到效应量之前"所作的决策。'),
        P('Treat heterogeneity as the finding when it is large. A pooled mean across studies that genuinely disagree is less informative than an account of why they disagree.',
          '当异质性很大时，应把它当作发现本身。对确实彼此分歧的研究求合并均值，其信息量低于对"为何分歧"的解释。'),
      ]),

    # -------------------------------------------------------------- case study
    D('case-study',
      era='Long practised; codified as a design with explicit procedures from the 1980s, and reporting transparency tightened from the 2010s.',
      era_zh='实践历史悠久，1980 年代起被编纂为有明确程序的研究设计，2010 年代起报告透明度收紧。',
      situation=[
        P('Some questions are about process and context: how something unfolded, why it took the form it did, what had to be in place. A variable-based design cannot answer these without first knowing what the variables are.',
          '有些问题关乎过程与情境：某事如何展开、为何呈现此种形态、需要哪些前提。变量式设计在尚不知道变量是什么时无法回答这类问题。'),
        P('The case study was codified to make this defensible rather than anecdotal, by specifying how cases are selected, how evidence is assembled, and how a claim is traced back to it.',
          '案例研究被编纂成型，正是为了让这类研究可辩护而非流于轶事：明确案例如何选取、证据如何汇集、主张如何回溯至证据。'),
      ],
      argument=[
        P('Case selection is theoretical, not statistical. A case is chosen because it is typical, extreme, critical, or theoretically informative, and the selection logic is part of the argument rather than a limitation.',
          '案例选择是理论性的而非统计性的。选择某案例是因为它典型、极端、关键或在理论上有信息量，而这一选择逻辑是论证的一部分，不是局限。'),
        P('Multiple sources are triangulated so that a claim rests on more than one kind of evidence, and a chain of evidence links the research question through the data to the conclusion so a reader can follow the inference.',
          '多源证据相互三角互证，使主张不只依赖单一类型的证据；证据链把研究问题经由数据连到结论，使读者能够跟随推理过程。'),
        P('Generalization is analytical: to theory, not to a population. A case can show that a mechanism exists and how it operates; it cannot establish how common it is.',
          '推广是分析性的：推广到理论而非总体。案例能表明某机制存在及其运作方式，却无法确立它有多普遍。'),
      ],
      development=[
        P('Multiple-case designs with explicit cross-case comparison became the norm for theory building, on the argument that replication logic across cases strengthens the account.',
          '带有明确跨案例比较的多案例设计成为理论构建的常规，其理由是跨案例的复制逻辑能强化解释。'),
      ],
      debates=[
        Debate('Does a single case support a general claim?', '单一案例能支撑一般性主张吗？',
               [Pos('Analytical-generalization position',
                    'A single critical case can refute a general claim or demonstrate that a mechanism is possible, which is a real contribution.',
                    '单一关键案例可以证伪一般性主张，或表明某机制是可能的——这本身就是实质贡献。'),
                Pos('Replication position',
                    'Without cross-case comparison there is no way to tell which features of the account are general and which are specific to the case.',
                    '缺少跨案例比较，就无从判断解释中哪些特征具有一般性、哪些只属于该案例。')],
               'Both accepted; which applies depends on whether the contribution is existence, refutation, or a general pattern.',
               '两种立场都被接受；适用哪一种，取决于贡献究竟是"存在性"、"证伪"还是"一般模式"。'),
      ],
      theoretical=[
        P('Selecting cases on the outcome — studying only successes — cannot support a claim about what causes it, because the comparison that would disconfirm the account is absent by construction.',
          '按结果选案例——只研究成功者——无法支撑关于成因的主张，因为能够证伪该解释的比较从设计上就被排除了。'),
        P('Case boundaries are a researcher decision. What counts as inside the case determines what can be explained, and shifting the boundary changes the finding.',
          '案例边界由研究者决定。什么算在案例之内，决定了什么可以被解释；边界移动，发现随之改变。'),
      ],
      empirical=[
        P('Retrospective accounts dominate, and participants reconstruct the process knowing how it ended, which systematically tidies contingency into strategy.',
          '回溯性叙述占主导，参与者是在已知结局的情况下重构过程，这会系统性地把偶然整理成战略。'),
        P('Access is negotiated, and organizations that grant it differ from those that refuse, so the case set is shaped by who was willing to be studied.',
          '进入现场需要协商，而同意的组织与拒绝的组织存在差异，因此案例集是由"谁愿意被研究"所塑造的。'),
      ],
      temporal=[
        P('Reporting standards changed within the last decade. Studies published before roughly 2015 often present conclusions with limited visibility into case selection, data structure, or how informants map to claims, which would now be asked for. That is a reporting difference, not automatically a quality difference.',
          '报告标准在过去十年发生变化。约 2015 年前发表的研究常常在案例选择、数据结构、受访者与主张的对应关系上可见度有限，而这些如今都会被要求呈现。这是报告差异，不自动等同于质量差异。'),
        P('Field access itself changed: much organizational activity now leaves a digital trace that can be observed without being present, and remote fieldwork alters what a researcher can see, so a case built on interviews and documents is not equivalent to one built on sustained presence.',
          '进入现场的方式本身也变了：大量组织活动如今留下可远程观察的数字痕迹，远程田野改变了研究者能看到什么；因此基于访谈与文档的案例，与基于长期在场的案例并不等同。'),
      ],
      today=[
        P('State the selection logic, the boundary, and the chain of evidence. These are what separate a case study from a well-written account of something that happened.',
          '应说明选择逻辑、案例边界与证据链。正是它们把案例研究与"关于某事的好文章"区分开。'),
        P('Include disconfirming evidence and rival explanations explicitly. A case that only supports the emerging account has not been tested against anything.',
          '应明确纳入反面证据与竞争性解释。只支持既有解释的案例，其实没有经受任何检验。'),
      ]),

    # --------------------------------------------------------- thematic analysis
    D('thematic-analysis',
      era='Codified as a named six-phase method in 2006; its authors substantially restated it as reflexive thematic analysis from 2019.',
      era_zh='2006 年被编纂为具名的六阶段方法，2019 年起其作者将其大幅重述为"反身性主题分析"。',
      situation=[
        P('Qualitative researchers were doing something recognizable across studies — coding a corpus and reporting patterns — but without a named procedure they could cite, so the analysis section was often unreproducible.',
          '质性研究者在做一件跨研究可辨认的事——对语料编码并报告模式——却没有可引用的具名程序，因此分析部分往往无法复现。'),
        P('Codifying the phases gave the method a citable standard and made the analytic steps visible, which is why it spread rapidly across fields with no qualitative tradition.',
          '把阶段编纂成型，为该方法提供了可引用的标准，也使分析步骤变得可见——这正是它在缺乏质性传统的领域中迅速扩散的原因。'),
      ],
      argument=[
        P('Six phases: familiarization with the data, generating initial codes across the whole corpus, collating codes into candidate themes, reviewing themes against extracts and the full dataset, defining and naming them, and writing up with illustrative extracts.',
          '六个阶段：熟悉数据；在全部语料上生成初始编码；把编码归并为候选主题；对照摘录与整体数据集检视主题；界定并命名主题；配以代表性摘录完成写作。'),
        P('A theme is an analytic construction with a central organizing concept, not a topic that appeared frequently. Reporting the most common subjects in the data is summarizing, not thematic analysis.',
          '主题是围绕某个核心组织概念的分析性建构，而非"出现频率高的话题"。报告数据中最常见的题目是概括，不是主题分析。'),
      ],
      development=[
        P('The reflexive restatement made the researcher role explicit: themes are produced through interpretation rather than discovered in the data, which changes what counts as a quality claim.',
          '反身性重述把研究者角色显式化：主题是经由解读产生的，而非从数据中被发现——这改变了什么才算质量主张。'),
      ],
      debates=[
        Debate('Does inter-coder reliability improve a thematic analysis?', '编码者间信度能提升主题分析的质量吗？',
               [Pos('Reliability position',
                    'Agreement statistics demonstrate that coding is not idiosyncratic and satisfy reviewers from quantitative traditions.',
                    '一致性统计量表明编码并非因人而异，也能满足来自量化传统的评审。'),
                Pos('Reflexive position',
                    'Agreement measures assume a correct coding exists to be recovered; in an interpretive analysis the researcher position is a resource, and a kappa answers a question the method is not asking.',
                    '一致性指标假定存在可被还原的"正确编码"；在解读性分析中研究者立场是资源，而 kappa 回答的是该方法并未提出的问题。')],
               'Open and genuinely methodological: the answer depends on whether the study is coding to a predefined frame or constructing themes interpretively.',
               '未决且是真正的方法论分歧：答案取决于研究是按预设框架编码，还是以解读方式建构主题。'),
      ],
      theoretical=[
        P('The method is theoretically flexible, which means the epistemological position has to be stated. The same six phases serve a realist coding exercise and an interpretive analysis, and they are not the same study.',
          '该方法在理论上是灵活的，因此必须陈述认识论立场。同样的六个阶段既可服务于实在论式编码，也可服务于解读性分析，而二者不是同一种研究。'),
        P('Prevalence of a theme is not its importance. A pattern appearing in two interviews can be the analytic contribution while one appearing in all of them is background.',
          '主题的普遍性不等于其重要性。只出现在两次访谈中的模式可能才是分析贡献，而出现在所有访谈中的可能只是背景。'),
      ],
      empirical=[
        P('Themes are frequently reported as topic summaries with quotations attached, which is the most common way the method is cited but not performed.',
          '主题常被报告为"配了引语的话题总结"——这是该方法最常见的"被引用而未被执行"的方式。'),
        P('Extracts are selected by the analyst, so a reader cannot tell how representative they are unless the analysis reports how the theme was distributed and what contradicted it.',
          '摘录由分析者选定，除非分析报告主题如何分布、有什么与之矛盾，否则读者无从判断摘录的代表性。'),
      ],
      temporal=[
        P('A large body of work cites the 2006 paper while performing something the same authors later explicitly distinguished from their method. Reading a pre-2019 thematic analysis, it is usually necessary to check what was actually done rather than relying on the citation.',
          '大量研究引用 2006 年的论文，实际做的却是其作者后来明确与自身方法区分开的东西。阅读 2019 年前的主题分析时，通常需要核对实际做法，而不能依赖引用。'),
        P('Corpora changed. The method was written for interview transcripts of manageable length; applying it unmodified to large digital text collections shifts it toward content analysis without the sampling and reliability apparatus that would require.',
          '语料也变了。该方法是为篇幅可控的访谈转录稿而写；不加修改地用于大规模数字文本集合，会使它滑向内容分析，却缺少后者所需的抽样与信度装置。'),
      ],
      today=[
        P('State the epistemological position and which version of the method is being used, then show the coding trail. Citing the 2006 paper is not a substitute for describing what was done.',
          '应陈述认识论立场与所采用的方法版本，并展示编码路径。引用 2006 年的论文不能替代对实际做法的描述。'),
        P('Report what did not fit. An analysis with no negative cases has either an unusually clean dataset or an under-examined interpretation.',
          '应报告不吻合的部分。没有反面案例的分析，要么数据集异常干净，要么解读检视不足。'),
      ]),
])
