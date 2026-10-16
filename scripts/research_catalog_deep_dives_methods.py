# -*- coding: utf-8 -*-
"""Deep dives for catalog methods.

Same schema as the theory dives, different questions. For a method the blocks
read as: what inferential problem it was built for, how the inference actually
works, how the method evolved, which methodological disputes are open, and which
of its limits are assumptions that bite, which are practice failures, and which
are bound to the period when its standard recipe was written.

Schema helpers live in ``research_catalog_deep_dives``. Content here is written
analysis, not extracted text.
"""

from research_catalog_deep_dives import D, Debate, P, Pos

METHOD_DIVES = dict([

    # ---------------------------------------------------------------------- DiD
    D('difference-in-differences',
      era='In use since the 19th century; the two-way fixed-effects recipe standardized in the 1990s and shown to be biased under staggered adoption between 2018 and 2021.',
      era_zh='19 世纪即有雏形，双向固定效应写法于 1990 年代成为标准，2018—2021 年被证明在错时处理下有偏。',
      situation=[
        P('Researchers wanted causal estimates from policies and events they could not randomize. A simple before-and-after comparison confounds the intervention with everything else that changed over the same period.',
          '研究者希望从无法随机化的政策与事件中得到因果估计。而单纯的前后比较，会把干预与同期发生的其他一切变化混在一起。'),
        P('Adding an untreated comparison group solves that specific problem: whatever else changed over the period should have affected both groups, so subtracting the control group change removes it.',
          '加入未受处理的对照组恰好解决这一问题：期间发生的其他变化应同时影响两组，因此减去对照组的变化即可将其消去。'),
      ],
      argument=[
        P('The estimator differences twice: once over time within each group, once across groups. What survives is the change in the treated group that the control group did not experience.',
          '该估计量做两次差分：先在每组内部对时间差分，再在组间差分。剩下的就是处理组经历而对照组未经历的变化。'),
        P('Everything rests on parallel trends — the assumption that without treatment, the two groups would have moved together. This is untestable, because it concerns an outcome that never occurred; pre-trend inspection tests an implication of it, not the assumption itself.',
          '一切都压在平行趋势上——即若无处理，两组本会同步变动。该假定不可检验，因为它关乎从未发生的结果；检查处理前趋势检验的是它的一个推论，而非假定本身。'),
      ],
      development=[
        P('The two-way fixed-effects specification became the default because it is a single regression that handles many units and periods at once. That convenience is what made the staggered-adoption problem so widespread.',
          '双向固定效应写法成为默认，因为它用一个回归就能同时处理多单位多时期。正是这种便利，使错时处理问题传播得如此之广。'),
        P('A wave of estimators was developed to fix it, differing in how they build clean comparisons and in what they assume about effect heterogeneity. Choosing among them is now part of the method rather than a technicality.',
          '一批新估计量被开发出来修正该问题，它们在如何构造干净比较、以及对效应异质性作何假定上各不相同。在它们之间做选择，如今已是方法本身的一部分，而非技术细节。'),
      ],
      debates=[
        Debate('Does a flat pre-trend justify the parallel-trends assumption?', '处理前趋势平坦能否证成平行趋势假定？',
               [Pos('Common practice',
                    'An insignificant pre-trend test is reported as evidence that the assumption holds.',
                    '把处理前趋势检验不显著报告为"假定成立"的证据。'),
                Pos('Methodological critique',
                    'Non-rejection with imprecise pre-period estimates is weak evidence, and conditioning the analysis on passing the test distorts inference.',
                    '在处理前估计不精确的情况下"未拒绝"是弱证据，而以通过该检验为条件继续分析会扭曲推断。')],
               'The critique is accepted; the practice persists. Reporting pre-period precision alongside the test is the current expectation.',
               '批评已被接受，做法却仍在延续。当前的期待是：在报告检验的同时给出处理前估计的精度。'),
      ],
      theoretical=[
        P('Parallel trends is an assumption about a counterfactual and cannot be verified by any amount of data. Every design decision either makes it more plausible or does not, and the argument is substantive rather than statistical.',
          '平行趋势是关于反事实的假定，任何数据量都无法验证它。每一个设计决策只能让它更可信或不然，其论证是实质性的而非统计性的。'),
        P('The estimand is the average effect on the treated in the observed period. It does not license claims about what would happen if the policy were extended to the control group.',
          '其估计目标是处理组在观察期内的平均效应，不足以支撑"若把政策推广到对照组会如何"的主张。'),
      ],
      empirical=[
        P('Control groups are frequently chosen for data availability rather than comparability, and the choice is rarely justified against alternatives in the reported analysis.',
          '对照组常按数据可得性而非可比性选择，且报告中很少针对备选方案论证这一选择。'),
        P('Standard errors are often clustered at the wrong level; with few treated clusters, conventional inference substantially overstates precision.',
          '标准误常聚类在错误层级；当处理组簇数很少时，常规推断会严重高估精度。'),
      ],
      temporal=[
        P('The standard recipe published before roughly 2018 is not safe for staggered adoption. Under two-way fixed effects with units treated at different times, already-treated units serve as controls for later-treated ones, and with heterogeneous effects the estimate can be a weighted average with negative weights — capable of returning the wrong sign. A large body of pre-2020 published work used exactly this specification.',
          '大约 2018 年之前发表的标准写法，在错时处理下并不安全。双向固定效应下，先受处理的单位会充当后受处理单位的对照；当效应存在异质性时，估计值可能是含负权重的加权平均——足以给出错误符号。2020 年前大量已发表研究用的正是这一写法。'),
        P('The event-study plot is now expected rather than optional, and reviewers increasingly require an estimator robust to heterogeneous timing. A paper that follows a textbook from the 2000s will be asked to redo the analysis.',
          '事件研究图如今是必需而非可选，评审也越来越要求使用对错时处理稳健的估计量。照搬 2000 年代教科书的论文会被要求重做分析。'),
      ],
      today=[
        P('If adoption is simultaneous, the classic specification remains correct. If it is staggered, use an estimator designed for it and report why you chose that one.',
          '若处理同时发生，经典写法依然正确；若是错时发生，应使用为此设计的估计量，并说明为何选它。'),
        P('Spend the argument on the control group and the assumption, not on the regression. The credibility of a DiD paper is decided before any estimation happens.',
          '论证的重心应放在对照组与假定上，而非回归本身。一篇 DiD 论文的可信度在任何估计发生之前就已决定。'),
      ]),

    # ---------------------------------------------------------------------- SEM
    D('structural-equation-modeling',
      era='Synthesized from path analysis and factor analysis in the 1970s; standard in survey-based management research from the 1990s.',
      era_zh='1970 年代由路径分析与因子分析综合而成，1990 年代起成为问卷类管理研究的标准工具。',
      situation=[
        P('Survey research faced two problems at once: the constructs of interest are not directly observable, and the hypotheses form a system in which one variable is both an outcome and a predictor.',
          '问卷研究同时面临两个问题：关注的构念不可直接观察；假设构成一个系统，其中同一变量既是结果又是预测因子。'),
        P('Handling them separately — first averaging items into a scale, then running regressions — throws away measurement error and cannot estimate the system jointly. SEM estimates both layers at once.',
          '分开处理——先把题项平均成量表、再跑回归——会丢弃测量误差，也无法联合估计整个系统。SEM 同时估计这两层。'),
      ],
      argument=[
        P('The model has two parts. The measurement model links observed indicators to latent factors; the structural model specifies relationships among those factors. Estimation finds parameters that best reproduce the observed covariance matrix.',
          '模型分两部分：测量模型把观测指标连到潜变量；结构模型设定潜变量之间的关系。估计过程寻找能最好复现观测协方差矩阵的参数。'),
        P('Because it fits a covariance structure, SEM tells you whether a model is consistent with the data. It does not tell you the model is correct, and many different models can fit the same covariance matrix equally well.',
          '由于它拟合的是协方差结构，SEM 能告诉你模型是否与数据一致，却不能告诉你模型是正确的；许多不同模型可以同样好地拟合同一协方差矩阵。'),
      ],
      development=[
        P('Partial least squares variants were adopted for smaller samples and prediction-oriented work, with an ongoing dispute about whether they support the same inferential claims.',
          '偏最小二乘变体被用于小样本与偏预测的研究，而它们能否支撑同样的推断主张，至今仍有争论。'),
      ],
      debates=[
        Debate('Do fit indices tell you the model is right?', '拟合指标能说明模型正确吗？',
               [Pos('Common practice',
                    'Meeting conventional thresholds is reported as evidence that the hypothesized model is supported.',
                    '达到常规阈值被报告为"假设模型获得支持"的证据。'),
                Pos('Methodological position',
                    'Fit indicates consistency with the covariance structure only; equivalent models with opposite causal orderings fit identically.',
                    '拟合只表明与协方差结构一致；因果方向相反的等价模型拟合完全相同。')],
               'Settled in the methods literature, widely ignored in applications. Reporting equivalent models is still rare.',
               '方法学文献已有定论，应用中却普遍被忽视。报告等价模型仍属罕见。'),
      ],
      theoretical=[
        P('Causal direction comes from the researcher, not the data. The arrows are assumptions, and reversing them frequently produces a model that fits just as well.',
          '因果方向来自研究者而非数据。箭头是假定，把它们反转往往能得到拟合同样好的模型。'),
        P('Reflective and formative measurement imply different things about the indicator-construct relationship, and misspecifying one as the other biases the structural estimates.',
          '反映型与形成型测量对"指标—构念"关系的含义不同，把二者设错会使结构估计有偏。'),
      ],
      empirical=[
        P('Modification indices are routinely used to improve fit, after which the model is reported as confirmatory. That is exploratory model search presented as a test.',
          '修正指数被例行用于改善拟合，随后模型却被报告为验证性的。这是把探索性的模型搜索当作检验来呈现。'),
        P('Sample size requirements scale with the number of parameters, and underpowered models produce unstable estimates that vary substantially across samples.',
          '样本量需求随参数数量增长，而功效不足的模型会产生在样本间大幅波动的不稳定估计。'),
      ],
      temporal=[
        P('The method assumes a cross-sectional covariance matrix from a single administration is adequate for estimating a causal system. That assumption was more defensible when the alternative was a single regression; today, panel and experimental designs are usually available and reviewers increasingly expect one.',
          '该方法假定单次施测的横截面协方差矩阵足以估计一个因果系统。当替代方案只是单个回归时，这一假定尚可辩护；如今面板与实验设计通常可得，评审也越来越期待采用其一。'),
        P('The reporting conventions were established when fit indices were the main evidence available. Preregistration and open materials have shifted the standard toward showing the model was specified before the data were seen.',
          '其报告惯例确立于"拟合指标是主要可用证据"的时期。预注册与材料开放已把标准转向"证明模型是在看到数据之前设定的"。'),
      ],
      today=[
        P('Specify the model in advance and report it whether or not it fits. A model that fits after modification is a hypothesis for the next study, not a result of this one.',
          '应事先设定模型，无论拟合与否都如实报告。经修正后才拟合的模型是下一项研究的假设，而不是本项研究的结果。'),
        P('Cross-sectional SEM cannot establish mediation. If the claim is about a process, the design needs temporal separation regardless of how well the model fits.',
          '横截面 SEM 无法确立中介效应。若主张关乎过程，无论模型拟合多好，设计都必须具备时间分离。'),
      ]),

    # ---------------------------------------------------------------- mediation
    D('mediation',
      era='Popularized by a stepwise procedure in 1986; the procedure superseded by bootstrap indirect-effect tests from the 2000s.',
      era_zh='1986 年因一套逐步法而普及，2000 年代起该逐步法被自助法间接效应检验取代。',
      situation=[
        P('Researchers wanted to say not just that X affects Y but how. Mediation offered a way to put a mechanism into a testable model rather than leaving it in the discussion section.',
          '研究者不仅想说 X 影响 Y，还想说清"如何影响"。中介分析提供了把机制放进可检验模型的方式，而不是留在讨论部分。'),
        P('The stepwise procedure that popularized it was easy to follow and became near-universal, which is why its known problems propagated so widely.',
          '使其普及的那套逐步法易于照做、近乎通用，这也是它的已知问题传播如此之广的原因。'),
      ],
      argument=[
        P('The total effect is decomposed into an indirect path running through the mediator and a direct path that does not. The indirect effect is the product of the two constituent paths.',
          '总效应被分解为经由中介变量的间接路径与不经由它的直接路径。间接效应是两段构成路径的乘积。'),
        P('Because that product is not normally distributed, its confidence interval must be obtained by bootstrapping rather than by the normal-theory approximation the original procedure used.',
          '由于该乘积不服从正态分布，其置信区间必须通过自助法获得，而非原逐步法所用的正态近似。'),
      ],
      development=[
        P('The requirement of a significant total effect before testing mediation was dropped: an indirect effect can exist when the total effect is suppressed by an opposing direct path.',
          '"检验中介前必须有显著总效应"的要求已被放弃：当直接路径方向相反并起抑制作用时，间接效应仍可存在。'),
        P('Causal mediation analysis reframed the problem in potential-outcomes terms, making explicit the assumption about mediator-outcome confounding that the regression approach leaves implicit.',
          '因果中介分析以潜在结果框架重述该问题，把回归法隐而不宣的"中介—结果混淆"假定显式化。'),
      ],
      debates=[
        Debate('Can cross-sectional data support a mediation claim?', '横截面数据能支撑中介主张吗？',
               [Pos('Common practice',
                    'A significant bootstrapped indirect effect from a single survey is reported as evidence of the mechanism.',
                    '把单次问卷中显著的自助法间接效应报告为机制的证据。'),
                Pos('Methodological position',
                    'Mediation is inherently temporal; estimating it from one time point yields a number that can be badly biased in either direction relative to the longitudinal quantity.',
                    '中介本质上是时间性的；用单一时点估计得到的数值，相对于纵向量可能在任一方向上严重偏倚。')],
               'Settled against cross-sectional mediation in the methods literature; still the most common design in applied journals.',
               '方法学文献已明确否定横截面中介，但它仍是应用期刊中最常见的设计。'),
      ],
      theoretical=[
        P('Identification requires no unmeasured confounding of the mediator-outcome relationship. Randomizing X does not randomize the mediator, so this assumption is untested in almost every experimental mediation study.',
          '识别要求中介与结果之间不存在未测混淆。随机化 X 并不随机化中介，因此几乎所有实验性中介研究都未检验这一假定。'),
        P('The decomposition assumes no treatment-mediator interaction unless it is explicitly modelled; where the effect of the mediator depends on treatment, the standard product term is not the quantity of interest.',
          '除非显式建模，分解过程假定处理与中介之间无交互；当中介的作用依赖于处理时，标准乘积项并非所关心的量。'),
      ],
      empirical=[
        P('Measurement error in the mediator attenuates the indirect path and inflates the direct path, so unreliable mediators systematically understate mechanism and overstate direct effect.',
          '中介变量的测量误差会衰减间接路径、抬高直接路径，因此不可靠的中介会系统性低估机制、高估直接效应。'),
        P('Indirect effects are frequently tested for many candidate mediators without adjustment, and only the surviving one is reported.',
          '常见做法是对多个候选中介逐一检验而不作校正，只报告存活下来的那一个。'),
      ],
      temporal=[
        P('The stepwise procedure that made the method popular is now considered wrong on two counts — the total-effect requirement and the normal-theory test — yet a large body of published findings rests on it. Results estimated that way should not be read as equivalent to bootstrapped estimates.',
          '使该方法普及的逐步法如今在两点上被认为是错的——总效应前提与正态近似检验——但大量已发表结论正建立在它之上。以那种方式得到的结果，不应与自助法估计等同看待。'),
        P('Reviewer expectations moved faster than textbooks. A design that was publishable in 2010 with a single-wave indirect effect will now usually be asked for temporal separation or a sensitivity analysis.',
          '评审期待的变化快于教科书。2010 年凭单波次间接效应即可发表的设计，如今通常会被要求时间分离或敏感性分析。'),
      ],
      today=[
        P('Separate the measurements in time and say why the chosen interval matches the theorized process. An arbitrary two-week gap is not temporal separation, it is a delay.',
          '应在时间上分离测量，并说明所选间隔为何与设想的过程相匹配。任意的两周间隔不是时间分离，只是延迟。'),
        P('Report a sensitivity analysis for mediator-outcome confounding. Without it the indirect effect is an association given the model, not evidence of a mechanism.',
          '应报告针对中介—结果混淆的敏感性分析。缺少它，间接效应只是给定模型下的关联，而非机制的证据。'),
      ]),

    # --------------------------------------------------------------- moderation
    D('moderation',
      era='Standard practice since the 1980s; power and reporting problems documented repeatedly from the 1990s onward.',
      era_zh='1980 年代起成为标准做法，功效与报告问题自 1990 年代起被反复记录。',
      situation=[
        P('Main effects rarely hold everywhere. Theory usually predicts that a relationship is stronger in some conditions than others, and moderation is how that boundary condition becomes testable.',
          '主效应很少处处成立。理论通常预测某关系在某些条件下更强，而调节分析正是把这一边界条件变得可检验的方式。'),
        P('This is where much theoretical contribution now lives: showing when an established effect reverses or disappears is often more publishable than showing it exists.',
          '当下大量理论贡献正落在这里：证明一个既有效应何时反转或消失，往往比证明它存在更容易发表。'),
      ],
      argument=[
        P('A product term is added to the model. Its coefficient estimates how much the slope of X on Y changes per unit of the moderator, and the constituent terms then represent effects at moderator equal to zero.',
          '模型中加入乘积项。其系数估计的是调节变量每增加一个单位、X 对 Y 斜率的变化量；此时构成项代表调节变量取零时的效应。'),
        P('Centring does not change the interaction coefficient or the model fit; it changes what the constituent terms mean, which is why uncentred results are so often misread as main effects.',
          '中心化不改变交互系数，也不改变模型拟合；它改变的是构成项的含义——这正是未中心化结果常被误读为主效应的原因。'),
      ],
      development=[
        P('Simple slopes and the Johnson-Neyman technique replaced the convention of probing at plus and minus one standard deviation, which reports effects at values that may not exist in the data.',
          '简单斜率与 Johnson-Neyman 技术取代了"在正负一个标准差处探查"的惯例，后者报告的效应所对应的取值在数据中可能并不存在。'),
      ],
      debates=[
        Debate('Are published interaction effects credible?', '已发表的交互效应可信吗？',
               [Pos('Power critique',
                    'Detecting an interaction needs several times the sample of a main effect; most published interactions are underpowered, so significant ones are inflated by selection.',
                    '检测交互所需样本是主效应的数倍；多数已发表交互功效不足，因而显著者会被选择性抬高。'),
                Pos('Defence',
                    'Field data with real variation in the moderator can detect meaningful interactions, and preregistered tests avoid the selection problem.',
                    '调节变量存在真实变异的现场数据可以检出有意义的交互，预注册检验也能避免选择问题。')],
               'The power critique is widely accepted; the reporting practice has changed slowly.',
               '功效批评已被广泛接受，报告实践的改变则很缓慢。'),
      ],
      theoretical=[
        P('A product term tests a specific functional form — linear-by-linear. A genuine boundary condition may be a threshold or a non-monotonic pattern that this specification cannot represent.',
          '乘积项检验的是特定函数形式——线性乘线性。真正的边界条件可能是阈值或非单调模式，而该设定无法表达。'),
        P('Statistical moderation and theoretical boundary condition are not the same thing; a significant interaction can be an artefact of scaling or of a non-linear main effect.',
          '统计上的调节与理论上的边界条件并非一回事；显著的交互可能只是量表尺度或非线性主效应造成的假象。'),
      ],
      empirical=[
        P('Interactions are underpowered far more often than main effects, and the required sample is rarely computed in advance.',
          '交互的功效不足远比主效应常见，而所需样本量很少被事先计算。'),
        P('Simple slopes are commonly plotted beyond the observed range of the moderator, which extrapolates the model into regions with no data.',
          '简单斜率常被绘制到调节变量观测范围之外，等于把模型外推到没有数据的区域。'),
      ],
      temporal=[
        P('The convention of testing several interactions and reporting the significant one was normal practice before preregistration. A substantial share of the older moderation literature was produced under that norm and should be read as exploratory regardless of how it is written.',
          '在预注册出现之前，"检验多个交互、只报告显著者"是常规做法。相当一部分较早的调节文献正是在这一规范下产生的，无论其行文如何，都应作为探索性结果来读。'),
        P('Sample sizes considered adequate when the practice was established are now known to be far too small for interaction detection, so replication failures in this literature are expected rather than surprising.',
          '该做法确立时被认为足够的样本量，如今已知远不足以检出交互，因此这一文献中的复制失败是可以预期的，而非意外。'),
      ],
      today=[
        P('Predict the direction in advance, power the study for the interaction rather than the main effect, and plot only over the observed range.',
          '应事先预测方向、按交互而非主效应计算功效，并只在观测范围内作图。'),
        P('If several moderators were tested, say so. An unreported multiplicity is the difference between a finding and a coincidence.',
          '若检验了多个调节变量，应如实说明。未报告的多重检验，正是"发现"与"巧合"之间的差别。'),
      ]),

    # ----------------------------------------------------------- topic modeling
    D('topic-modeling',
      era='Introduced in 2003; adopted across the social sciences from around 2010 as corpora became routinely available.',
      era_zh='2003 年提出，约 2010 年起随语料普及被社会科学广泛采用。',
      situation=[
        P('Researchers gained access to corpora far too large to read — filings, transcripts, reviews, posts — and needed some principled way to describe what was in them without hand coding every document.',
          '研究者得到了大到无法阅读的语料——申报文件、会议记录、评论、帖子——需要一种有原则的方式描述其内容，而不必对每份文档手工编码。'),
        P('The appeal was that structure could be induced from the corpus itself rather than imposed by a codebook written in advance, which suited exploratory work in domains without established categories.',
          '其吸引力在于结构可以从语料自身归纳出来，而非由事先编写的编码手册强加，这适合缺乏既定类别的探索性研究。'),
      ],
      argument=[
        P('Documents are modelled as mixtures over latent topics, and topics as distributions over words. Fitting recovers both, so each document gets a set of topic proportions and each topic a ranked word list.',
          '文档被建模为潜在主题的混合，主题被建模为词的分布。拟合同时还原两者：每份文档获得一组主题比例，每个主题获得一份排序词表。'),
        P('The model does not know what a topic means. It finds statistical regularities in word co-occurrence; the interpretation is supplied entirely by the researcher reading the output.',
          '模型并不知道主题意味着什么。它找到的是词共现的统计规律；解释完全由阅读输出的研究者提供。'),
      ],
      development=[
        P('Structural variants allow document metadata to affect topic prevalence, which lets the model answer comparative questions directly rather than through a second-stage regression.',
          '结构化变体允许文档元数据影响主题占比，使模型能直接回答比较性问题，而不必依赖第二阶段回归。'),
        P('Embedding-based clustering has displaced it for many tasks, though it inherits the same validation burden and adds sensitivity to the embedding model version.',
          '基于嵌入的聚类在许多任务上已取而代之，但它继承了同样的验证负担，并新增了对嵌入模型版本的敏感性。'),
      ],
      debates=[
        Debate('Are induced topics valid measures?', '归纳出的主题是有效测量吗？',
               [Pos('Inductive position',
                    'Topics recover meaningful structure that a predetermined codebook would miss, which is the point of using the method.',
                    '主题能还原预设编码手册会遗漏的有意义结构，这正是使用该方法的意义。'),
                Pos('Validation position',
                    'Without human validation against documents, a topic is a word list; using its proportions as a variable in a regression imports unvalidated measurement into the result.',
                    '若不对照文档做人工验证，主题只是一份词表；把其比例当作变量放进回归，等于把未经验证的测量带入结论。')],
               'Increasingly settled in favour of requiring validation, though downstream use of unvalidated proportions remains common.',
               '越来越倾向于"必须验证"，但把未验证的主题比例用于下游分析的做法仍很普遍。'),
      ],
      theoretical=[
        P('The number of topics is a researcher choice that changes the result substantially, and no criterion selects it uniquely; coherence and held-out likelihood often disagree.',
          '主题数是由研究者选定的，它会显著改变结果，且没有唯一的选取标准；连贯性与留出似然常常给出不同答案。'),
        P('The bag-of-words assumption discards order and syntax, so negation, attribution, and irony are invisible to the model.',
          '词袋假定丢弃了词序与句法，因此否定、引述与反讽对模型不可见。'),
      ],
      empirical=[
        P('Preprocessing choices — stopwords, stemming, minimum frequency, n-grams — change the topics materially and are frequently reported in a single sentence or not at all.',
          '预处理选择——停用词、词干化、最低频次、n-gram——会实质性改变主题，而它们常常只用一句话带过，甚至完全不报告。'),
        P('Results vary across random seeds; reporting one run without a stability check leaves the reader unable to tell signal from initialization.',
          '结果随随机种子变化；只报告一次运行而不做稳定性检查，读者无法区分信号与初始化。'),
      ],
      temporal=[
        P('The method was adopted when the alternative was reading nothing at all, and standards were correspondingly loose. Now that classification with a validated codebook and modern language models is feasible at similar cost, an unvalidated topic model is harder to justify as a measurement strategy.',
          '该方法被采用时，替代方案是"什么都读不了"，标准也因此宽松。如今以经验证的编码手册配合现代语言模型进行分类，成本相当且可行，未经验证的主题模型作为测量策略已更难辩护。'),
        P('Its assumptions were designed for long, topically coherent documents. Short social text, multilingual corpora, and machine-generated text all violate them in ways the original evaluation did not cover.',
          '其假定是为篇幅较长、主题连贯的文档设计的。短社交文本、多语语料与机器生成文本都以原始评估未覆盖的方式违反这些假定。'),
      ],
      today=[
        P('Treat it as an exploratory instrument that produces hypotheses, then validate the categories against documents before using them as variables.',
          '应把它当作产生假设的探索性工具，在把类别当作变量使用之前，先对照文档验证。'),
        P('Report preprocessing, topic number criterion, seed, and human validation results. Without those four, the analysis is not reproducible even in principle.',
          '应报告预处理、主题数的选取标准、随机种子与人工验证结果。缺少这四项，分析在原则上就不可复现。'),
      ]),

    # --------------------------------------------------------------- experiment
    D('experiment',
      era='Long established; standards reshaped substantially by the replication crisis from 2011 onward.',
      era_zh='方法本身历史悠久，但其标准自 2011 年起被复制危机大幅重塑。',
      situation=[
        P('Observational data cannot separate the effect of a factor from everything correlated with it. Randomization solves that at the source: if assignment is random, treatment is independent of everything, observed or not.',
          '观察数据无法把某因素的效应与所有与之相关之物分开。随机化从源头解决了这一问题：若分配是随机的，处理便独立于一切因素，无论是否被观测。'),
        P('This is the only design that delivers that guarantee without an identifying assumption, which is why it anchors causal claims wherever manipulation is possible and ethical.',
          '这是唯一无需识别性假定即可提供该保证的设计，因此只要操纵在可行且合乎伦理的范围内，因果主张便以它为基准。'),
      ],
      argument=[
        P('Random assignment makes the groups exchangeable in expectation, so the difference in outcomes estimates the average treatment effect. Everything else in the design exists to protect that property.',
          '随机分配使各组在期望意义上可交换，因而结果差异即估计平均处理效应。设计中的其余安排，都是为保护这一性质而存在。'),
        P('The threats are concrete: attrition that differs by condition, a manipulation that moves something other than the intended construct, and analytic choices made after seeing the outcome.',
          '威胁是具体的：因条件而异的样本流失；操纵改变了非目标构念；以及在看到结果之后才作出的分析选择。'),
      ],
      development=[
        P('Preregistration, power analysis, and open materials became normal expectations rather than optional virtues, and reporting standards now cover exclusions and deviations explicitly.',
          '预注册、功效分析与材料开放已从可选美德变为常规期待，报告标准也明确涵盖排除与偏离。'),
      ],
      debates=[
        Debate('Does experimental control buy generalizability?', '实验控制能换来外部效度吗？',
               [Pos('Internal-validity priority',
                    'Establish the causal effect cleanly first; generalization is a separate question answered by replication in new settings.',
                    '先干净地确立因果效应；推广是另一个问题，由在新情境中的复制来回答。'),
                Pos('External-validity critique',
                    'Effects estimated on convenience samples in artificial tasks may not exist in the field, and the literature has repeatedly found this.',
                    '在人工任务与便利样本上估出的效应，可能在现场并不存在，文献已反复发现这一点。')],
               'Both are accepted; the practical answer is that a single experiment establishes an effect in a setting, not a general law.',
               '两者都被接受；实践上的答案是：单个实验确立的是某一情境中的效应，而非普遍规律。'),
      ],
      theoretical=[
        P('Randomization identifies the effect of the manipulation, not of the construct the manipulation is meant to represent. A confounded manipulation gives an unbiased estimate of the wrong thing.',
          '随机化识别的是"操纵"的效应，而非操纵所要代表的构念的效应。被混淆的操纵会对错误的对象给出无偏估计。'),
        P('The estimand is an average. Where effects are heterogeneous, the average can be positive while the effect is negative for a substantial subgroup.',
          '其估计目标是平均值。当效应异质时，平均值可以为正，而某个相当规模的子群体效应为负。'),
      ],
      empirical=[
        P('Exclusion rules applied after seeing outcomes break randomization; attention-check exclusions are the most common route by which this happens without being noticed.',
          '在看到结果之后应用的排除规则会破坏随机化；注意力检查排除是最常见、也最不易被察觉的途径。'),
        P('Manipulation checks that are themselves affected by the outcome cannot establish that the manipulation worked.',
          '本身会被结果影响的操纵检查，无法证明操纵是有效的。'),
      ],
      temporal=[
        P('A large body of pre-2011 experimental work was produced before preregistration, with small samples and flexible analysis. Those findings should be treated as provisional regardless of how confidently they are cited, and several canonical effects have not survived replication.',
          '大量 2011 年前的实验研究产生于预注册之前，样本小、分析弹性大。无论它们被多么自信地引用，都应视为暂定；若干经典效应并未通过复制检验。'),
        P('Online panels made large samples cheap, which fixed the power problem and introduced new ones: inattentive respondents, professional participants, and now automated responses that look like human data.',
          '在线样本池使大样本变得廉价，解决了功效问题，也带来新问题：不专心的受访者、职业受试者，以及如今看起来像人类数据的自动化作答。'),
      ],
      today=[
        P('Preregister the hypotheses, the exclusions, and the analysis. The value of the design comes from committing before the data exist, and it is lost the moment choices are made afterwards.',
          '应预注册假设、排除规则与分析方案。该设计的价值来自"在数据存在之前作出承诺"，一旦事后再作选择，价值即告丧失。'),
        P('For online samples, plan for automated and inattentive responses in the sampling design rather than filtering them out after the fact, since post-hoc filtering is itself a threat to randomization.',
          '使用在线样本时，应在抽样设计阶段就考虑自动化与不专心作答，而不是事后过滤——事后过滤本身就威胁随机化。'),
      ]),

    # ---------------------------------------------------- instrumental variables
    D('instrumental-variables',
      era='Developed in econometrics from the 1920s; the credibility-revolution standards for instrument justification date from the 1990s.',
      era_zh='1920 年代起在计量经济学中发展，工具变量论证的"可信性革命"标准形成于 1990 年代。',
      situation=[
        P('Regression cannot recover a causal effect when the regressor is correlated with the error — through simultaneity, omitted variables, or measurement error. Controls do not solve this; they only address confounders that are observed.',
          '当回归变量与误差项相关时——由于联立、遗漏变量或测量误差——回归无法还原因果效应。加控制变量解决不了这一问题，它只能处理被观测到的混淆。'),
        P('An instrument supplies variation in the regressor that is unrelated to the error, so the part of the variation that is exogenous can be isolated and used.',
          '工具变量提供了与误差无关的、regressor 上的变异，从而可以分离并利用其中外生的那部分。'),
      ],
      argument=[
        P('Three conditions must hold together: the instrument predicts the endogenous regressor, it is as good as randomly assigned, and it affects the outcome only through that regressor.',
          '三个条件必须同时成立：工具能预测内生变量；它如同随机分配；且它只经由该变量影响结果。'),
        P('The third condition, exclusion, is not testable in the just-identified case. It is defended by argument about the setting, and no statistic can substitute for that argument.',
          '第三个条件"排他性"在恰好识别的情形下不可检验。它只能通过对情境的论证来辩护，任何统计量都无法替代这一论证。'),
        P('With heterogeneous effects the estimate is local: it applies to the subpopulation whose behaviour the instrument actually moved, not to everyone.',
          '在效应异质时，估计是局部的：它适用于其行为确实被工具改变的那部分子群体，而非全体。'),
      ],
      development=[
        P('Weak-instrument diagnostics and robust confidence sets were developed after it became clear that a low first-stage F produces estimates more biased than the OLS they were meant to fix.',
          '在人们认识到"第一阶段 F 值低会使估计比它本欲修正的 OLS 更有偏"之后，弱工具诊断与稳健置信集被发展出来。'),
      ],
      debates=[
        Debate('What counts as an acceptable instrument?', '什么才算可接受的工具变量？',
               [Pos('Design-based position',
                    'Only instruments arising from a plausibly exogenous shock or rule qualify, and the argument must be substantive.',
                    '只有来自可信外生冲击或规则的工具才合格，且论证必须是实质性的。'),
                Pos('Availability-driven practice',
                    'Lagged values, industry averages, and geographic distances are widely used because they are available and pass the first-stage test.',
                    '滞后值、行业均值与地理距离被广泛使用，因为它们可得且能通过第一阶段检验。')],
               'The design-based standard has won in economics; availability-driven instruments remain common in adjacent fields.',
               '设计导向标准在经济学中已占上风；可得性驱动的工具在相邻领域仍很常见。'),
      ],
      theoretical=[
        P('Exclusion is an assumption about the world that data cannot check. A strong first stage is evidence about relevance only and says nothing about exclusion.',
          '排他性是关于世界的假定，数据无法核查。第一阶段强只是关于相关性的证据，对排他性一无所言。'),
        P('The local estimand is frequently reported as if it were the population effect, which changes what the finding actually supports.',
          '局部估计目标常被当作总体效应报告，而这会改变该发现实际支撑的结论。'),
      ],
      empirical=[
        P('Weak instruments bias the estimate toward OLS and make conventional confidence intervals badly undercover; the first-stage F must be reported, and thresholds once considered adequate are now known to be too low.',
          '弱工具会使估计向 OLS 偏倚，并使常规置信区间的覆盖率严重不足；必须报告第一阶段 F 值，而曾被认为足够的阈值现已知偏低。'),
        P('Overidentification tests are often cited as evidence of validity, but they only test whether multiple instruments agree, which they can do while all being invalid in the same way.',
          '过度识别检验常被引为有效性证据，但它只检验多个工具是否一致——而它们完全可能以同样的方式全都无效。'),
      ],
      temporal=[
        P('A generation of instruments accepted in the 1990s and 2000s — lagged regressors, industry means, rainfall, distance — have since been shown to violate exclusion in many of the settings where they were used. Older results relying on them should not be read at face value.',
          '1990—2000 年代被接受的一代工具——滞后回归变量、行业均值、降雨量、距离——此后被证明在许多使用情境中违反排他性。依赖它们的旧结果不应按表面价值解读。'),
        P('Reporting standards changed substantially: what passed review as an instrument twenty years ago would now typically require a documented shock, a first-stage F far above the old rule of thumb, and a sensitivity analysis for exclusion violations.',
          '报告标准已大幅改变：二十年前能通过评审的工具，如今通常需要有据可查的冲击、远高于旧经验法则的第一阶段 F 值，以及针对排他性违背的敏感性分析。'),
      ],
      today=[
        P('Spend the paper on why the exclusion restriction holds in this setting. If that argument is not convincing, no diagnostic will rescue the design.',
          '论文的重心应放在"为何排他性在本情境下成立"。若该论证不能服人，任何诊断都救不了这个设计。'),
        P('State the compliant subpopulation the estimate applies to, and report a sensitivity analysis for small violations of exclusion rather than treating it as binary.',
          '应说明估计适用于哪一"依从"子群体，并针对排他性的小幅违背报告敏感性分析，而不是把它当作非黑即白。'),
      ]),

    # ------------------------------------------------------- qualitative interviews
    D('interviews',
      era='Long established across the social sciences; reporting and transparency standards tightened substantially from the 2010s.',
      era_zh='在社会科学中历史悠久，报告与透明度标准自 2010 年代起显著收紧。',
      situation=[
        P('Surveys constrain answers to categories the researcher wrote in advance. When the phenomenon is not well enough understood to write those categories, that constraint destroys the information the study needs.',
          '问卷把回答限制在研究者事先写好的类别里。当现象尚未被充分理解、无法写出这些类别时，这一限制恰恰摧毁了研究所需的信息。'),
        P('Interviews trade standardization for access to the participant own framing, which is the right trade when the research question is what is going on rather than how much.',
          '访谈以放弃标准化换取进入受访者自身框架的机会；当研究问题是"发生了什么"而非"有多少"时，这是正确的取舍。'),
      ],
      argument=[
        P('Sampling is purposive, not random: participants are selected because they can speak to the phenomenon, and the logic of that selection is part of the contribution rather than a limitation to apologize for.',
          '抽样是目的性的而非随机的：选择受访者是因为他们能就该现象发言，而这一选择逻辑本身是贡献的一部分，不是需要致歉的局限。'),
        P('Analysis and collection interleave. What is learned in early interviews reshapes later ones, which is a feature of the design and the reason a fixed protocol is not required.',
          '分析与收集交错进行。早期访谈所得会重塑后续访谈，这是该设计的特性，也是不必固守既定提纲的原因。'),
      ],
      development=[
        P('Reporting conventions moved from presenting conclusions to showing the trail: sampling rationale, interview counts, coding structure, and the relationship between data extracts and claims.',
          '报告惯例已从"呈现结论"转向"展示路径"：抽样理由、访谈数量、编码结构，以及数据摘录与主张之间的对应关系。'),
      ],
      debates=[
        Debate('What does saturation mean and can it be claimed?', '饱和意味着什么，能否被宣称？',
               [Pos('Conventional use',
                    'Saturation is reached when additional interviews stop producing new codes, and reporting the number reached is sufficient.',
                    '当新增访谈不再产生新编码时即达到饱和，报告所达数量即为充分。'),
                Pos('Critical position',
                    'Saturation is frequently asserted without any stated procedure, and the number of interviews is often set by resources rather than by the analysis.',
                    '饱和常在无任何既定程序的情况下被断言，访谈数量往往由资源而非分析决定。')],
               'Increasingly settled toward requiring the procedure to be described rather than the term invoked.',
               '越来越倾向于要求描述具体程序，而非仅仅援引该术语。'),
      ],
      theoretical=[
        P('Interviews collect accounts, not behaviour. An account is evidence about how a person represents and justifies what they did, which is a different object from what they did.',
          '访谈收集的是叙述而非行为。叙述是关于"一个人如何表述与辩护其所为"的证据，与"其所为"是不同的对象。'),
        P('The researcher is part of the instrument. Who asks, how the question is framed, and what the participant thinks the research is for all shape the account.',
          '研究者本身是工具的一部分。谁在问、问题如何框定、受访者认为研究意在何为，都会塑造所得叙述。'),
      ],
      empirical=[
        P('Selective quotation is difficult for a reader to detect, which is why the analysis needs to show disconfirming cases rather than only the extracts that support the theme.',
          '选择性引述对读者而言难以察觉，因此分析必须呈现不支持的案例，而不只是支持主题的摘录。'),
        P('Retrospective accounts are reconstructed with knowledge of the outcome, which systematically tidies the process being described.',
          '回溯性叙述是在已知结果的情况下重构的，这会系统性地把所描述的过程"整理"得更整齐。'),
      ],
      temporal=[
        P('Standards changed within the last decade. Studies published before roughly 2015 frequently report a sample size and a claim of saturation with no coding trail, which would now be asked to show the procedure. That is a reporting gap, not necessarily a quality gap, and older work should be read accordingly.',
          '标准在过去十年内发生了变化。约 2015 年前发表的研究常常只报告样本量与"已达饱和"的说法，而无编码路径；如今则会被要求展示程序。这是报告上的差距，未必是质量上的差距，阅读旧研究时应作此区分。'),
        P('Remote interviewing became standard practice after 2020. It changes access, rapport, and who can participate, and treating a video interview corpus as equivalent to an in-person one is an assumption rather than a given.',
          '远程访谈在 2020 年后成为常规做法。它改变了接触方式、融洽关系与可参与的人群；把视频访谈语料等同于面对面语料是一项假定，而非理所当然。'),
      ],
      today=[
        P('Report the sampling logic, the guide, the coding structure, and how saturation was judged. The credibility of the study rests on the trail being visible, not on the number of interviews.',
          '应报告抽样逻辑、访谈提纲、编码结构，以及如何判断饱和。研究的可信度取决于路径是否可见，而非访谈数量。'),
        P('Say what the accounts are evidence of. A study that treats interview reports as direct evidence of behaviour is claiming more than the design supports.',
          '应说明这些叙述是关于什么的证据。把访谈报告当作行为的直接证据，是在主张超出设计所能支撑的东西。'),
      ]),
])
