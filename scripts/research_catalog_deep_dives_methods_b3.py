# -*- coding: utf-8 -*-
"""Deep dives for catalog methods, batch 3.

Multilevel and measurement models, one more design-based causal method, network
analysis, and the two remaining qualitative methods named in the corpus.

Schema helpers live in ``research_catalog_deep_dives``.
"""

from research_catalog_deep_dives import D, Debate, P, Pos

METHOD_DIVES_B3 = dict([

    # ------------------------------------------------------ multilevel modeling
    D('multilevel-modeling',
      era='Available from the 1980s; became standard in organizational research from the late 1990s as software made it routine.',
      era_zh='1980 年代即已可用，1990 年代末随软件普及成为组织研究的标准工具。',
      situation=[
        P('Organizational data are nested: employees in teams, teams in units, students in schools. Observations from the same group are not independent, which violates the assumption ordinary regression rests on.',
          '组织数据具有嵌套结构：员工在团队中、团队在单元中、学生在学校中。同组观测并不独立，这违反了普通回归所依赖的假定。'),
        P('Ignoring the nesting understates standard errors, sometimes severely, so effects that are not there appear significant. The alternative of aggregating to the group level discards individual variation and can reverse the sign of a relationship.',
          '忽略嵌套会低估标准误，有时相当严重，使本不存在的效应显得显著。而聚合到组层面的做法会丢弃个体变异，甚至可能使关系的符号反转。'),
      ],
      argument=[
        P('The model estimates variance at each level simultaneously. The intercept can vary across groups, capturing that some teams simply score higher; the slope can vary too, capturing that a relationship is stronger in some teams than others.',
          '模型同时估计各层的方差。截距可以在组间变动，刻画"某些团队整体得分更高"；斜率也可以变动，刻画"某种关系在某些团队中更强"。'),
        P('The intraclass correlation reports how much of the total variance sits between groups, which is the empirical justification for using the model at all.',
          '组内相关系数报告总方差中有多少落在组间，这正是使用该模型的经验依据。'),
        P('Centring is not a technicality. Group-mean centring separates the within-group effect from the between-group effect; grand-mean centring leaves them conflated, and the two answer different questions.',
          '中心化不是技术细节。组均值中心化把组内效应与组间效应分开；总均值中心化则使二者混杂——它们回答的是不同问题。'),
      ],
      development=[
        P('Cross-level interactions extended it to ask whether a group-level variable moderates an individual-level relationship, which is where most organizational theory actually lives.',
          '跨层交互把它扩展为追问"组层面变量是否调节个体层面关系"——而多数组织理论的主张恰恰在这里。'),
      ],
      debates=[
        Debate('How many groups are needed?', '需要多少个组？',
               [Pos('Rules-of-thumb position',
                    'Commonly cited minimums around thirty groups are adequate for fixed effects, and studies routinely proceed on that basis.',
                    '常被引用的"约三十组"下限对固定效应而言足够，研究常据此推进。'),
                Pos('Simulation-based position',
                    'Variance components and cross-level interactions need far more groups than fixed effects, and the common minimums produce badly biased variance estimates.',
                    '方差成分与跨层交互所需的组数远多于固定效应，常见下限会产生严重有偏的方差估计。')],
               'The simulation evidence is accepted; practice still frequently relies on the older rule of thumb.',
               '模拟证据已被接受，实践中仍常沿用较旧的经验法则。'),
      ],
      theoretical=[
        P('A multilevel model handles dependence; it does not establish that a group-level construct exists. Aggregating individual perceptions into a team score requires demonstrated agreement, which is a separate claim.',
          '多层模型处理的是依赖性，并不证明组层面构念存在。把个体感知聚合为团队分数需要先证明一致性，这是另一项主张。'),
        P('Cross-level interaction requires a random slope for the lower-level predictor. Testing the interaction without it assumes the relationship is identical across groups, which is what the hypothesis denies.',
          '跨层交互要求低层预测变量具有随机斜率。不设随机斜率就检验交互，等于假定该关系在各组间完全相同——而这正是假设所否认的。'),
      ],
      empirical=[
        P('The number of level-2 units is frequently too small for the variance components being estimated, and the resulting estimates are unstable across samples.',
          '第二层单位数常常不足以估计所设定的方差成分，由此得到的估计在样本间不稳定。'),
        P('Centring decisions are often unreported, which makes it impossible for a reader to tell whether a coefficient is a within-group or a conflated effect.',
          '中心化决策常常不被报告，读者因此无法判断某个系数是组内效应还是混杂效应。'),
      ],
      temporal=[
        P('Standard practice was established with two-level designs of modest size — a few hundred individuals in a few dozen teams — collected by survey. High-frequency data nested within persons over many occasions have different properties, and the sample-size guidance developed for the older designs does not transfer directly.',
          '标准做法确立于规模适中的两层设计——数百名个体、数十个团队、以问卷收集。个体内多时点的高频数据性质不同，为旧设计发展出的样本量指引无法直接迁移。'),
        P('Software made the models routine faster than reporting standards caught up, so a substantial body of work fits multilevel models without reporting the intraclass correlation or the centring, which are the two things needed to interpret the result.',
          '软件使这类模型迅速普及，而报告标准跟进较慢；因此有相当一批研究拟合了多层模型，却不报告组内相关与中心化方式——而这恰是解读结果所必需的两项信息。'),
      ],
      today=[
        P('Report the intraclass correlation, the centring, and the number of groups. Without those three the model cannot be evaluated by a reader.',
          '应报告组内相关、中心化方式与组数。缺少这三项，读者无法评估该模型。'),
        P('If the hypothesis is cross-level, include the random slope and power the study for it rather than for the main effect.',
          '若假设是跨层的，应纳入随机斜率，并按交互而非主效应计算功效。'),
      ]),

    # -------------------------------------------------- regression discontinuity
    D('regression-discontinuity',
      era='Introduced in 1960; largely dormant until the credibility revolution revived it from the late 1990s.',
      era_zh='1960 年提出，长期沉寂，直至 1990 年代末"可信性革命"将其复兴。',
      situation=[
        P('Many consequential treatments are assigned by a rule rather than by randomization: a scholarship above a test score, a subsidy below a size threshold, a rating that triggers inspection.',
          '许多重要的处理是按规则而非随机分配的：分数线以上给奖学金、规模阈值以下给补贴、评级触发检查。'),
        P('That rule is usually a nuisance for identification, since assignment is deterministic in the running variable. The insight is that it is an opportunity: right at the cutoff, units on either side are nearly identical.',
          '这一规则通常被视为识别上的麻烦，因为分配由驱动变量确定性决定。洞见在于：这恰恰是机会——就在阈值两侧，单位几乎完全相同。'),
      ],
      argument=[
        P('If units cannot precisely control which side of the cutoff they land on, then near the threshold assignment is as good as random, and the jump in the outcome at the cutoff estimates the treatment effect there.',
          '若单位无法精确控制自己落在阈值哪一侧，那么在阈值附近分配就如同随机；结果在阈值处的跳跃即估计该处的处理效应。'),
        P('The identifying assumption is continuity: absent treatment, the outcome would have varied smoothly through the cutoff. Any jump is then attributable to the treatment rather than to something else changing at that point.',
          '识别假定是连续性：若无处理，结果本应平滑地穿过阈值。因此任何跳跃都可归因于处理，而非该点上其他因素的变化。'),
        P('The estimate is local by construction. It applies to units at the threshold and says nothing about units far from it, which is the honest cost of the design credibility.',
          '该估计在构造上就是局部的：它适用于阈值附近的单位，对远离阈值者无所言说——这是该设计可信度的诚实代价。'),
      ],
      development=[
        P('The fuzzy design extended it to cases where crossing the cutoff changes the probability of treatment rather than determining it, which is estimated as an instrumental variable at the threshold.',
          '模糊设计把它扩展到"跨过阈值改变处理概率而非决定处理"的情形，其估计相当于在阈值处使用工具变量。'),
        P('Data-driven bandwidth selection and bias-corrected inference replaced arbitrary window choices and global polynomial fits.',
          '数据驱动的带宽选择与偏差校正推断，取代了任意的窗口选择与全局多项式拟合。'),
      ],
      debates=[
        Debate('How should the functional form be chosen?', '函数形式应如何选择？',
               [Pos('Global polynomial practice',
                    'Fitting a high-order polynomial across the full range uses all the data and was standard for years.',
                    '在全区间拟合高阶多项式可以用上全部数据，多年来一直是标准做法。'),
                Pos('Local position',
                    'High-order polynomials give large weight to observations far from the cutoff and produce noisy, sometimes absurd estimates at it; local linear estimation within a chosen bandwidth is preferred.',
                    '高阶多项式给远离阈值的观测很大权重，在阈值处产生噪声大甚至荒谬的估计；应在选定带宽内使用局部线性估计。')],
               'Settled against global high-order polynomials. Papers using them should be read with that in mind.',
               '已明确否定全局高阶多项式。使用该做法的论文应带此认识来读。'),
      ],
      theoretical=[
        P('The estimate is a local average treatment effect at the cutoff. Extrapolating it to the whole population is the most common overclaim in applications of this design.',
          '该估计是阈值处的局部平均处理效应。把它外推到整个总体，是这一设计应用中最常见的过度主张。'),
        P('It requires that nothing else changes discontinuously at the same threshold. Where a single cutoff triggers several policies at once, the design cannot separate them.',
          '它要求同一阈值处没有其他因素发生跳跃。当单一阈值同时触发多项政策时，该设计无法把它们分开。'),
      ],
      empirical=[
        P('Manipulation of the running variable is the main threat, and a density test at the cutoff is the standard check; it is frequently omitted.',
          '驱动变量被操纵是主要威胁，阈值处的密度检验是标准检查，但它常被省略。'),
        P('Results are sensitive to bandwidth, and reporting a single bandwidth without a sensitivity analysis leaves the reader unable to judge robustness.',
          '结果对带宽敏感；只报告单一带宽而不做敏感性分析，读者无从判断稳健性。'),
      ],
      temporal=[
        P('Published work from before roughly 2010 commonly used global high-order polynomials and arbitrary bandwidths, and some of those estimates do not survive modern local estimation. Older results should not be treated as equivalent to those produced under current practice.',
          '约 2010 年之前发表的研究普遍使用全局高阶多项式与任意带宽，其中部分估计在现代局部估计下无法成立。旧结果不应与当前做法下产生的结果等同看待。'),
        P('The design assumes the assignment rule is fixed and known. Where thresholds are set by an algorithm that updates, or are undisclosed, the running variable and the cutoff may not be stable over the estimation window.',
          '该设计假定分配规则固定且已知。当阈值由会更新的算法设定、或并未公开时，驱动变量与阈值在估计窗口内可能并不稳定。'),
      ],
      today=[
        P('Run the density test and report bandwidth sensitivity. These two checks are what distinguish a credible discontinuity from a jump in a noisy plot.',
          '应做密度检验并报告带宽敏感性。这两项检查正是"可信的断点"与"噪声图上的一个跳跃"之间的区别。'),
        P('State the local estimand plainly. A result at the threshold is a strong finding; presenting it as a population effect weakens rather than strengthens the paper.',
          '应直白说明局部估计目标。阈值处的结果是有力发现；把它呈现为总体效应只会削弱而非增强论文。'),
      ]),

    # ---------------------------------------------- confirmatory factor analysis
    D('confirmatory-factor-analysis',
      era='Developed in the 1960s and 1970s; standard practice in survey research from the 1990s.',
      era_zh='1960—1970 年代发展成形，1990 年代起成为问卷研究的标准做法。',
      situation=[
        P('Exploratory factor analysis could describe how items grouped together but could not test whether a hypothesized structure held, because the structure was derived from the same data.',
          '探索性因子分析能描述题项如何聚合，却无法检验假设的结构是否成立——因为该结构本身就是从同一数据中得出的。'),
        P('Survey research needed a way to state a measurement model in advance and then test it, which is what separates measurement validation from measurement discovery.',
          '问卷研究需要一种"先设定测量模型、再加以检验"的方法——这正是测量验证与测量发现之间的区别。'),
      ],
      argument=[
        P('The researcher specifies which items load on which factors and which do not, then estimates the model and evaluates how well the implied covariance matrix reproduces the observed one.',
          '研究者先设定哪些题项负载于哪些因子、哪些不负载，再估计模型，并评估模型隐含的协方差矩阵在多大程度上复现了观测矩阵。'),
        P('The useful outputs are not the fit indices but the loadings, the reliability, and the discriminant validity evidence: whether items measure their intended factor and whether factors are distinguishable from one another.',
          '真正有用的产出不是拟合指标，而是负载、信度与区分效度证据：题项是否测量了其目标因子，以及各因子彼此能否区分。'),
        P('Measurement invariance is the extension that matters for comparison. Before comparing latent means across groups or over time, the model must show the items behave the same way in each.',
          '测量等值性是对比较而言最重要的扩展。在跨组或跨时点比较潜变量均值之前，必须证明题项在各组中的运作方式相同。'),
      ],
      development=[
        P('The heterotrait-monotrait ratio was introduced because the older discriminant-validity criterion was shown to miss a substantial share of cases where two constructs are not actually distinguishable.',
          '异质—单质相关比被引入，因为旧的区分效度标准被证明会漏掉相当一部分"两个构念实际无法区分"的情形。'),
      ],
      debates=[
        Debate('Are conventional fit thresholds meaningful?', '常规拟合阈值有意义吗？',
               [Pos('Threshold practice',
                    'Established cutoffs give a common standard and make results comparable across studies.',
                    '既定临界值提供了共同标准，使跨研究结果可比。'),
                Pos('Critical position',
                    'The cutoffs were derived under specific simulation conditions and do not generalize to different model sizes, sample sizes, or estimators; treating them as universal produces both false acceptance and false rejection.',
                    '这些临界值是在特定模拟条件下得出的，无法推广到不同的模型规模、样本量与估计量；把它们当作普适标准会同时造成误接受与误拒绝。')],
               'The critique is well established in methods writing; the thresholds continue to be applied as rules in applied journals.',
               '该批评在方法学写作中已确立，应用期刊中这些阈值仍被当作规则使用。'),
      ],
      theoretical=[
        P('It tests whether a specified structure is consistent with the data, not whether it is the right structure. Alternative models with different substantive meanings often fit equally well.',
          '它检验的是"设定的结构是否与数据一致"，而非"该结构是否正确"。含义不同的替代模型往往拟合得同样好。'),
        P('The reflective model assumes the construct causes the indicators. For constructs where the indicators define the construct, the model is misspecified and the estimates are not interpretable as intended.',
          '反映型模型假定构念导致指标。对于"指标定义构念"的情形，模型设定错误，其估计无法按预期解读。'),
      ],
      empirical=[
        P('Modification indices are commonly used to free residual correlations until the model fits, after which it is reported as confirmatory, which it no longer is.',
          '修正指数常被用来释放残差相关直至拟合，随后仍以验证性模型报告——而它已不再是验证性的。'),
        P('Discriminant validity is frequently asserted from a table without the correlation between factors being close to the threshold ever being addressed.',
          '区分效度常凭一张表格断言，而因子间相关是否逼近临界值这一点从未被处理。'),
      ],
      temporal=[
        P('Practice was established when a study administered one instrument to one sample at one time. Comparing groups or waves without testing invariance was common and is now considered a specification error, so older comparative results may rest on an untested assumption.',
          '这一做法确立于"一份工具、一个样本、一个时点"的研究情境。不检验等值性就比较组别或波次曾经很常见，如今被视为设定错误；因此较早的比较性结果可能建立在未经检验的假定之上。'),
        P('The reporting convention centred on fit indices because they were the main available evidence. Open data and preregistration have shifted the standard toward showing the model was specified before the data were seen, which fit indices cannot demonstrate.',
          '报告惯例以拟合指标为中心，因为它们曾是主要可用证据。数据开放与预注册已把标准转向"证明模型是在看到数据之前设定的"，而拟合指标无法证明这一点。'),
      ],
      today=[
        P('Report loadings, reliability, and discriminant validity rather than leading with fit indices, and test invariance before any group comparison.',
          '应报告负载、信度与区分效度，而不是以拟合指标开场；任何组间比较之前先检验等值性。'),
        P('If the model was modified, say so and treat the result as exploratory. A modified model needs a new sample before it can be called confirmed.',
          '若模型经过修正，应如实说明并把结果视为探索性的。修正后的模型需要新样本才能被称为已验证。'),
      ]),

    # -------------------------------------------------------- network analysis
    D('network-analysis',
      era='Sociometric roots in the 1930s; formalized from the 1970s and transformed by digital trace data from the 2000s.',
      era_zh='1930 年代有社会计量学根源，1970 年代形式化，2000 年代因数字痕迹数据而改观。',
      situation=[
        P('Standard statistical methods assume observations are independent. When the object of interest is the relationship between units, that assumption is not merely violated — it removes the phenomenon from the analysis.',
          '标准统计方法假定观测独立。当研究对象恰是单位之间的关系时，该假定不只是被违反——它把现象本身从分析中抹去了。'),
        P('Network analysis makes the tie the unit of observation and provides measures of position and structure that attribute-based methods have no way to express.',
          '网络分析把联结作为观测单位，并提供了基于属性的方法无法表达的位置与结构指标。'),
      ],
      argument=[
        P('The analysis starts with a boundary rule defining who is in the network, an edge definition saying what counts as a tie, and a decision about direction and weight. All three are researcher choices that determine everything downstream.',
          '分析始于三项设定：界定网络成员的边界规则、说明什么算作联结的边定义，以及方向与权重的决定。三者都是研究者的选择，并决定其后的一切。'),
        P('Position measures answer different questions: degree captures activity, betweenness captures brokerage, eigenvector captures connection to well-connected others. Choosing one without a theoretical reason invites reporting whichever correlates with the outcome.',
          '位置指标回答不同问题：度中心度刻画活跃度，中介中心度刻画中介性，特征向量中心度刻画"与高连接者相连"。缺乏理论依据地选取其一，等于在挑选与结果相关的那个来报告。'),
        P('Observed structure must be compared against a null model. Networks generated at random from the same degree distribution already show clustering, so an observed pattern is only evidence if it exceeds what chance produces.',
          '观察到的结构必须与零模型比较。由相同度分布随机生成的网络本就呈现聚集，因此观察到的模式只有在超出随机所能产生的程度时才构成证据。'),
      ],
      development=[
        P('Statistical models for networks were developed to handle the dependence directly rather than computing measures and feeding them into ordinary regression, which treats network-derived variables as independent observations.',
          '为网络发展出的统计模型直接处理依赖性，而不是先算指标再放进普通回归——后者把网络导出的变量当作独立观测。'),
      ],
      debates=[
        Debate('Can homophily and influence be separated?', '同质性与影响能被分开吗？',
               [Pos('Identification position',
                    'They are observationally equivalent in cross-sectional network data: similar people connect, and connected people become similar, and both produce the same correlation.',
                    '在横截面网络数据中二者观测等价：相似者相连，相连者变相似，两者产生同样的相关。'),
                Pos('Design position',
                    'Longitudinal network data, instruments, or randomized tie formation can separate them, but the required design is rarely available.',
                    '纵向网络数据、工具变量或随机化的联结形成可以把它们分开，但所需设计很少可得。')],
               'The problem is well established. Cross-sectional claims about social influence should be read as association.',
               '该问题已被充分确立。横截面上关于社会影响的主张应作为关联来读。'),
      ],
      theoretical=[
        P('Boundary specification is a theoretical decision presented as a technical one. Who is left out determines the structure, and measures are not comparable across studies that draw the boundary differently.',
          '边界设定是被当作技术问题呈现的理论决定。谁被排除在外决定了结构，边界划法不同的研究之间指标不可比。'),
        P('A tie in a digital trace is not the same object as a tie in a survey. Interaction logs record contact, not relationship, and the two answer different theoretical questions.',
          '数字痕迹中的联结与问卷中的联结不是同一对象。互动日志记录的是接触而非关系，二者回答不同的理论问题。'),
      ],
      empirical=[
        P('Missing ties bias every centrality measure, and coverage is rarely reported. Betweenness is the most sensitive, and it is also the most commonly used.',
          '遗漏联结会使每一个中心度指标产生偏倚，而覆盖情况很少被报告。中介中心度最为敏感，同时也最常被使用。'),
        P('Network measures fed into ordinary regression violate independence twice over, and standard errors computed that way are not interpretable.',
          '把网络指标放进普通回归会两次违反独立性，据此计算的标准误无法解读。'),
      ],
      temporal=[
        P('The measures were developed for small, carefully bounded, survey-elicited networks where a researcher could verify that a tie meant something. Digital trace networks are large and complete-looking but record whatever the platform logs, and applying measures designed for elicited ties to logged contact changes what is being estimated.',
          '这些指标是为小规模、边界严谨、由问卷获取的网络开发的，研究者能核实一条联结确有含义。数字痕迹网络规模大、看似完整，记录的却是平台所记录的内容；把为"问卷获取的联结"设计的指标套用到"日志接触"上，估计的对象已经改变。'),
        P('Null-model comparison was less critical when networks were small and structure was inspected by hand. At scale, almost any pattern will appear somewhere, and a finding without a null comparison is not interpretable.',
          '当网络规模小、结构可人工检视时，零模型比较不那么关键。在大规模数据中，几乎任何模式都会在某处出现；缺少零模型比较的发现无法解读。'),
      ],
      today=[
        P('State the boundary, the edge definition, and the missing-tie coverage before reporting any measure. These three determine whether the numbers mean anything.',
          '在报告任何指标之前，应说明边界、边定义与遗漏联结的覆盖情况。这三项决定了数字是否有意义。'),
        P('Choose the centrality measure from the theory and compare against a null model. Reporting several and discussing the significant one is a search, not a test.',
          '应依据理论选择中心度指标，并与零模型比较。报告多个指标却只讨论显著的那个，是搜索而非检验。'),
      ]),

    # --------------------------------------------------------- grounded theory
    D('grounded-theory',
      era='Introduced in 1967; split into divergent versions from the 1990s and frequently invoked without its procedures.',
      era_zh='1967 年提出，1990 年代起分化为不同版本，且经常被援引而不执行其程序。',
      situation=[
        P('Mid-century sociology was dominated by testing grand theory. Fields where no adequate theory existed had no legitimate method for building one, and inductive work was dismissed as merely descriptive.',
          '20 世纪中叶的社会学以检验宏大理论为主导。在缺乏适当理论的领域，没有合法的方法去构建理论，归纳性研究被当作单纯的描述而遭轻视。'),
        P('Grounded theory was an argument that theory generation is a legitimate, systematic activity with its own procedures, not a failure to test something.',
          '扎根理论主张：理论生成是一项正当且系统的活动，有其自身程序，而非"没能去检验什么"。'),
      ],
      argument=[
        P('Collection and analysis are interleaved from the start. Early coding shapes who is sampled next, which is theoretical sampling — sampling to develop a category rather than to represent a population.',
          '收集与分析从一开始就交错进行。早期编码决定接下来抽样谁，这就是理论抽样——为发展某个范畴而抽样，而非为代表某个总体。'),
        P('Constant comparison runs throughout: each new incident is compared with existing codes, which forces categories to be revised rather than confirmed.',
          '持续比较贯穿全程：每一个新事件都与已有编码比较，迫使范畴被修正而非被确认。'),
        P('Memo writing is the analysis, not a record of it. Categories are developed in memos, and saturation is reached when new data stop changing them.',
          '备忘录写作本身就是分析，而不是分析的记录。范畴在备忘录中被发展，当新数据不再改变范畴时即达到饱和。'),
      ],
      development=[
        P('The originators diverged: one version emphasized systematic coding procedures, the other insisted the analyst should not force data into a prescribed frame. A later constructivist version made the researcher role in producing the theory explicit.',
          '两位创始人分道扬镳：一个版本强调系统的编码程序，另一个坚持分析者不应把数据塞进既定框架。后来的建构主义版本则明确了研究者在生成理论中的角色。'),
      ],
      debates=[
        Debate('Should the researcher review the literature first?', '研究者应当先做文献回顾吗？',
               [Pos('Classical position',
                    'Prior literature imposes categories and prevents the theory from emerging from the data, so it should be delayed.',
                    '既有文献会强加范畴、妨碍理论从数据中涌现，因此应当推迟。'),
                Pos('Practical position',
                    'No researcher enters a field empty-headed, and pretending otherwise hides the assumptions rather than removing them; the literature should be engaged reflexively.',
                    '没有研究者是空着脑袋进入田野的；假装如此只是隐藏而非消除假定，文献应当被反身性地对待。')],
               'Open, and it divides the versions. What matters for a reader is that the study says which position it took.',
               '未决，且正是各版本的分野所在。对读者而言重要的是研究说明自己采取了哪一立场。'),
      ],
      theoretical=[
        P('Emergence is contested. A category does not emerge from data by itself; it is constructed by an analyst making choices, and the classical language obscures that.',
          '"涌现"存在争议。范畴不会自行从数据中涌现，而是由分析者作出选择建构出来的，古典表述掩盖了这一点。'),
        P('The output should be a theory — categories with stated relationships — not a list of themes. Much work labelled grounded theory stops at categorization.',
          '其产出应当是理论——带有明确关系的范畴——而非主题清单。大量以扎根理论为名的研究止步于分类。'),
      ],
      empirical=[
        P('Theoretical sampling requires the ability to return to the field and select new participants as categories develop. Studies with a fixed sample collected in advance cannot have done it, whatever they cite.',
          '理论抽样要求能够返回田野、随范畴发展选择新参与者。事先收集固定样本的研究不可能做到这一点，无论其引用了什么。'),
        P('Saturation is asserted far more often than its procedure is described, and the interview count is frequently determined by resources.',
          '饱和被断言的次数远多于其程序被描述的次数，而访谈数量常由资源决定。'),
      ],
      temporal=[
        P('The method was designed for fieldwork where the researcher could return repeatedly over months. Compressed research timelines and one-shot ethics approvals make genuine theoretical sampling difficult, and a large share of work citing the method uses a fixed sample, which is a different design.',
          '该方法针对的是研究者能在数月间反复返回田野的实地工作。压缩的研究周期与一次性伦理审批使真正的理论抽样变得困难；大量引用该方法的研究使用固定样本，那是另一种设计。'),
        P('Analysis software made coding faster and also made it easy to produce a code hierarchy that looks like grounded theory without constant comparison or memo-driven category development.',
          '分析软件使编码更快，也使人容易产出"看起来像扎根理论"的编码层级——却没有持续比较，也没有以备忘录驱动的范畴发展。'),
      ],
      today=[
        P('Say which version is being followed and show the theoretical sampling and memo trail. Without those, the study is qualitative analysis, which is a legitimate thing to call it.',
          '应说明遵循哪个版本，并展示理论抽样与备忘录轨迹。缺少它们，这项研究就是质性分析——而这本身是一个正当的名称。'),
        P('Deliver relationships between categories, not a taxonomy. A theory states how the categories connect and under what conditions.',
          '应交付范畴之间的关系，而非一套分类法。理论要说明范畴如何连接、在何种条件下连接。'),
      ]),

    # -------------------------------------------------------- content analysis
    D('content-analysis',
      era='Formalized for communication research in the mid-20th century; reliability standards established from the 1980s and 2000s.',
      era_zh='20 世纪中叶为传播研究形式化，信度标准在 1980 与 2000 年代确立。',
      situation=[
        P('Documents, media, and transcripts contain evidence about what organizations and people say, but reading them impressionistically produces conclusions no one else can check.',
          '文档、媒介与转录稿包含关于组织与个人所言的证据，但印象式阅读得出的结论无人能够核查。'),
        P('Content analysis was developed to make that evidence systematic: define categories in advance, apply them consistently, and demonstrate that a second coder would reach the same result.',
          '内容分析的发展正是为了让这类证据系统化：事先界定类别、一致地施加、并证明第二位编码者会得到相同结果。'),
      ],
      argument=[
        P('The design is fixed before coding: a sampling frame for documents, a unit of analysis, a codebook with inclusion and exclusion rules, and a reliability procedure on an independently double-coded subsample.',
          '设计在编码之前即已固定：文档的抽样框、分析单位、含纳入与排除规则的编码手册，以及在独立双编码子样本上的信度程序。'),
        P('Reliability is the load-bearing element and must account for chance agreement. Percentage agreement is not sufficient, since two coders applying a common category will agree often by chance alone.',
          '信度是承重要素，且必须扣除偶然一致。百分比一致度不够，因为两位编码者在常见类别上仅凭偶然也会经常一致。'),
        P('It differs from thematic analysis in intent: content analysis applies a predetermined frame and reports frequency and distribution, while thematic analysis constructs themes interpretively.',
          '它与主题分析在意图上不同：内容分析施加既定框架并报告频次与分布，主题分析则以解读方式建构主题。'),
      ],
      development=[
        P('Computational dictionary and classifier approaches extended the same logic to corpora too large to hand code, inheriting the requirement for validation against human coding.',
          '计算式词典与分类器方法把同一逻辑扩展到无法手工编码的大规模语料，并继承了"必须对照人工编码验证"的要求。'),
      ],
      debates=[
        Debate('Does frequency indicate importance?', '频次能表明重要性吗？',
               [Pos('Manifest-content position',
                    'Counting what is present is exactly the point: the method measures what a corpus contains, not what it means.',
                    '统计"出现了什么"正是要点：该方法测量语料包含什么，而非它意味着什么。'),
                Pos('Latent-content critique',
                    'What is emphasized, omitted, or implied often matters more than what is counted, and frequency can invert the interpretation.',
                    '被强调、被省略或被暗示的内容往往比被计数的更重要，频次甚至可能使解读反转。')],
               'Both are accepted for different questions. The error is claiming importance from a frequency table without an argument.',
               '两者各自适用不同问题。错误在于仅凭频次表就主张重要性而不加论证。'),
      ],
      theoretical=[
        P('Categories are theoretical commitments made in advance. What the codebook cannot express cannot be found, so the design determines the range of possible findings.',
          '类别是事先作出的理论承诺。编码手册无法表达之物就无法被发现，因此设计决定了可能发现的范围。'),
        P('The unit of analysis — word, sentence, paragraph, document — changes the result, and studies frequently do not justify the choice.',
          '分析单位——词、句、段、文档——会改变结果，而研究常常不为这一选择作论证。'),
      ],
      empirical=[
        P('Reliability is often reported as a single overall figure that hides categories where agreement was poor; per-category reliability is what a reader needs.',
          '信度常以单一总体数值报告，掩盖了那些一致性很差的类别；读者真正需要的是分类别信度。'),
        P('Codebooks are revised during coding without recoding earlier material, which means the corpus was not coded under one scheme.',
          '编码手册在编码过程中被修订却不回头重编早前材料，这意味着语料并非在同一套方案下完成编码。'),
      ],
      temporal=[
        P('The method was built for a bounded corpus a team could plausibly read. Applying it to web-scale collections shifts the constraint from coding effort to sampling, and a convenience sample of retrievable documents is not the sampling frame the method assumes.',
          '该方法针对的是团队有可能读完的有界语料。把它应用于网络规模的集合，约束从编码工作量转向抽样；而"可检索文档的便利样本"并非该方法所假定的抽样框。'),
        P('Automated coding is now routine, but the validation requirement did not change. A classifier applied without human-coded validation produces frequency tables with the appearance of content analysis and none of its evidentiary basis.',
          '自动化编码如今已成常规，但验证要求并未改变。未经人工编码验证就施加的分类器，产出的频次表徒具内容分析之形，而无其证据基础。'),
      ],
      today=[
        P('Report per-category reliability, the codebook version, and the double-coded subsample size. A single overall kappa is not enough to evaluate the coding.',
          '应报告分类别信度、编码手册版本与双编码子样本量。单一总体 kappa 不足以评估编码质量。'),
        P('If coding is automated, validate against hand coding on a random sample and report per-class performance, not overall accuracy.',
          '若编码是自动化的，应在随机样本上对照人工编码验证，并报告分类别表现而非总体准确率。'),
      ]),
])
