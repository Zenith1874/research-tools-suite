# -*- coding: utf-8 -*-
"""Deep dives for catalog constructs, batch 5 — highest remaining usage.

Eight constructs that appear heavily in the A* cache and were still carrying a
one-line record. Several are outcome variables whose measurement decisions
determine what a study can conclude, which is the recurring theme here.

Schema helpers live in ``research_catalog_deep_dives``.
"""

from research_catalog_deep_dives import D, Debate, P, Pos

CONSTRUCT_DIVES_B5 = dict([

    # ------------------------------------------------------------ event salience
    D('event-salience',
      era='Implicit in crisis and disruption research for decades; formalized as a dimension of event strength from 2015.',
      era_zh='数十年来隐含于危机与中断研究中，2015 年起被形式化为"事件强度"的一个维度。',
      situation=[
        P('Organizational research treated context as a set of standing conditions. That framing has no way to represent a discrete happening — an acquisition, an outage, a scandal — that changes behaviour precisely because it stands out from the ongoing flow.',
          '组织研究此前把情境当作一组持续存在的条件。这一框定无法表达离散事件——并购、宕机、丑闻——而这类事件恰恰因为从日常流程中凸显出来才改变行为。'),
        P('Event-based frameworks supplied the missing vocabulary: events differ in strength, and salience is the dimension that determines whether an event registers at all.',
          '基于事件的框架补上了缺失的词汇：事件在强度上有差异，而显著性正是决定"事件是否被注意到"的那个维度。'),
      ],
      argument=[
        P('Salience is composed of novelty, disruption, and criticality. A happening that is routine, absorbable, and peripheral does not function as an event even if it occurred.',
          '显著性由新颖性、破坏性与关键性构成。常规的、可被吸收的、边缘的发生，即便确实发生了，也不构成"事件"。'),
        P('It is relational rather than intrinsic. The same occurrence is salient to one unit and background to another, so salience must be specified for a stated actor or system.',
          '它是关系性的而非内在的。同一发生对一个单元是显著的、对另一个只是背景；因此显著性必须针对特定的行动者或系统来界定。'),
      ],
      development=[
        P('Event strength was decomposed further into salience, disruption, and duration, on the argument that a brief shock and a sustained one produce different organizational responses.',
          '事件强度被进一步分解为显著性、破坏性与持续时间，理由是短暂冲击与持续冲击引发的组织反应不同。'),
      ],
      debates=[
        Debate('Is salience a property of the event or of attention?', '显著性是事件的属性还是注意力的属性？',
               [Pos('Event property position',
                    'Novelty and disruption can be coded from the occurrence itself, which makes salience assessable independently of anyone reaction.',
                    '新颖性与破坏性可以从事件本身编码，这使显著性能够独立于任何人的反应被评估。'),
                Pos('Attention position',
                    'What registers depends on what the observer was already attending to, so salience is produced in the encounter rather than carried by the event.',
                    '什么会被注意到取决于观察者原本在关注什么；因此显著性产生于遭遇之中，而非由事件本身携带。')],
               'Open. The practical consequence is whether salience can be coded from archives or must be measured from participants.',
               '未决。其实践后果是：显著性能否从档案编码，还是必须从参与者处测量。'),
      ],
      theoretical=[
        P('Salience is frequently inferred from the response it is meant to explain, which makes the account circular unless it is coded independently.',
          '显著性常常从它本应解释的反应中反推出来；除非独立编码，否则该解释是循环的。'),
        P('The construct assumes events are discrete and bounded. Slow-moving changes that never become an event may matter more and are outside the frame.',
          '该构念假定事件是离散且有边界的。从未成为"事件"的缓慢变化可能更重要，却在框架之外。'),
      ],
      empirical=[
        P('Archival studies code salience from media coverage, which conflates the event with how much attention it received and biases toward events involving large or visible firms.',
          '档案研究以媒体报道量编码显著性，这把事件本身与它所获得的关注混为一谈，并偏向涉及大企业或高曝光企业的事件。'),
        P('Retrospective ratings are collected after the response is known, so participants reconstruct how salient the event felt in light of what followed.',
          '回溯性评分是在反应已知之后收集的，参与者会依据后续发展重构"当时感觉有多显著"。'),
      ],
      temporal=[
        P('The construct assumes a shared information environment where a salient event is salient to most of a unit at once. Where information arrives through personalized feeds, an event can be salient to some members and invisible to others in the same team, which the unit-level treatment does not represent.',
          '该构念假定存在共享信息环境：显著事件会同时对单元中多数人显著。当信息经由个性化推送到达时，同一团队中某些成员觉得显著、另一些完全没看到——单元层面的处理无法表达这一点。'),
        P('It was theorized when events were relatively rare against a stable background. Where disruption is frequent and overlapping, novelty erodes and the same objective occurrence produces less salience than the framework would predict.',
          '它成形于"事件相对稀少、背景稳定"的时期。当中断频繁且相互叠加时，新颖性被侵蚀，同样的客观发生所产生的显著性低于框架的预测。'),
      ],
      today=[
        P('Code salience independently of the outcome, and say for whom the event was salient. An event-level score without a referent actor is not interpretable.',
          '应独立于结果编码显著性，并说明该事件对谁而言显著。没有指称行动者的事件层面分数无法解读。'),
        P('If using media coverage, treat it as a measure of attention and control for firm visibility rather than reading it as event strength.',
          '若使用媒体报道量，应把它当作注意力的测量并控制企业曝光度，而不是直接读作事件强度。'),
      ]),

    # ----------------------------------------------------------- risk perception
    D('risk-perception',
      era='Established in the psychometric tradition from the late 1970s; extended by affect-based accounts from the 2000s.',
      era_zh='1970 年代末在心理测量传统中确立，2000 年代起被基于情绪的解释扩展。',
      situation=[
        P('Expert risk assessments and public reactions diverged systematically. Technologies with low expected fatalities provoked strong opposition while familiar hazards with higher tolls did not.',
          '专家的风险评估与公众反应系统性背离：预期死亡人数低的技术引发强烈反对，而伤亡更高的熟悉危险却不然。'),
        P('Treating that as public irrationality explained nothing. The alternative was to ask what dimensions people actually use when they judge risk, which turned out to be more than probability times magnitude.',
          '把它归为公众非理性什么也解释不了。替代做法是追问人们判断风险时实际使用哪些维度——结果远不止"概率乘以严重性"。'),
      ],
      argument=[
        P('Perceived risk loads on qualitative dimensions the technical definition omits: dread, controllability, voluntariness, catastrophic potential, familiarity, and whether effects are delayed.',
          '感知风险负载于技术定义所遗漏的质性维度：恐惧感、可控性、自愿性、灾难性潜势、熟悉度，以及影响是否延迟。'),
        P('The affect heuristic supplies a faster route: an overall good or bad feeling about an activity drives both perceived risk and perceived benefit, which is why the two are negatively correlated in judgement although they are often positively correlated in the world.',
          '情绪启发式提供了更快的路径：对某项活动的整体好恶同时驱动感知风险与感知收益——这正是二者在判断中负相关、而在现实中往往正相关的原因。'),
        P('The practical implication is that risk communication that supplies more probability information often fails, because probability is not the dimension driving the judgement.',
          '实践含义是：提供更多概率信息的风险沟通经常失效，因为概率并非驱动该判断的维度。'),
      ],
      development=[
        P('Cultural and worldview accounts added that risk judgements track group commitments, which explains why the same evidence produces polarized assessments.',
          '文化与世界观解释补充道：风险判断追随群体立场——这解释了为何同样的证据会产生两极化的评估。'),
      ],
      debates=[
        Debate('Is divergence from expert assessment a bias?', '与专家评估的背离算偏差吗？',
               [Pos('Normative position',
                    'Where perceived risk departs from expected harm, decisions will misallocate attention and resources.',
                    '当感知风险偏离预期危害时，决策会错误配置注意力与资源。'),
                Pos('Dimensional position',
                    'People are evaluating dread, control, and fairness, which are legitimate considerations the expert measure excludes by construction.',
                    '人们评估的是恐惧、控制与公平，这些是专家指标在构造上就排除掉的正当考量。')],
               'Largely settled toward the second: the divergence reflects different dimensions rather than error, though both readings persist in policy debate.',
               '基本倾向于后者：背离反映的是不同维度而非错误，尽管两种解读在政策辩论中并存。'),
      ],
      theoretical=[
        P('Risk perception and risk attitude are distinct — how risky something is judged to be, versus willingness to bear it — and are frequently measured with overlapping items.',
          '风险感知与风险态度是不同的——"判断某事有多危险"与"愿不愿意承担它"——却常以重叠的题项测量。'),
        P('The construct is domain specific. General risk-taking scales predict poorly for a specific hazard, which limits transferring findings across domains.',
          '该构念是领域特定的。通用风险承担量表对具体危险的预测很差，这限制了跨领域迁移结论。'),
      ],
      empirical=[
        P('Most evidence uses hypothetical scenarios where no outcome is borne, and stated risk perception is a poor predictor of behaviour under real exposure.',
          '多数证据使用不承担任何后果的假想情境；而陈述性风险感知对真实暴露下的行为预测很差。'),
        P('Question framing moves the response substantially, so the elicitation method is part of the measurement rather than a neutral channel.',
          '提问框架会大幅改变回答，因此引出方法是测量的组成部分，而非中性通道。'),
      ],
      temporal=[
        P('The dimensional structure was established for physical and environmental hazards — radiation, chemicals, transport. Algorithmic and data risks load differently: they are invisible, delayed, involuntary, and hard to attribute, and instruments built for physical hazards may not capture what people object to.',
          '维度结构是针对实体与环境危险确立的——辐射、化学品、交通。算法与数据风险的负载方式不同：不可见、延迟、非自愿、难以归因；为实体危险构建的量表可能捕捉不到人们真正反对的东西。'),
        P('It was studied when hazard information came from institutions with identifiable credibility. Where risk information is encountered through algorithmic feeds and contested online, the trust component of the judgement operates on a different object than the framework assumed.',
          '它的研究发生在"危险信息来自可辨识可信度的机构"的时期。当风险信息经由算法推送、并在网上被争议时，判断中的信任成分所作用的对象已不同于框架的假定。'),
      ],
      today=[
        P('Measure the qualitative dimensions rather than a single risk rating; a global score hides which dimension is driving the judgement and therefore what a communication should address.',
          '应测量质性维度而非单一风险评分；总体分数掩盖了究竟哪个维度在驱动判断，也就掩盖了沟通应针对什么。'),
        P('For algorithmic risk, check that the instrument covers invisibility, attribution difficulty, and lack of recourse, which the classic dimensions do not.',
          '研究算法风险时，应检查量表是否覆盖不可见性、归因困难与缺乏救济——经典维度并不涵盖这些。'),
      ]),

    # ---------------------------------------------------------------- workload
    D('workload',
      era='Studied in ergonomics from the 1960s and in occupational stress research since; the standard job-demand measure.',
      era_zh='1960 年代起在人因工程中研究，此后进入职业压力研究，是标准的工作要求指标。',
      situation=[
        P('Stress research needed a demand variable that applies across jobs. Task-specific measures could not be compared, and a general measure was required to build a cumulative literature.',
          '压力研究需要一个可跨职业适用的要求变量。任务特定的指标无法比较，要建立可累积的文献就需要通用测量。'),
        P('Workload became that variable, defined perceptually as the quantity, pace, and intensity of demands rather than as an objective count of tasks.',
          '工作负荷成为这一变量，其定义是主观感知的任务数量、节奏与强度，而非客观的任务计数。'),
      ],
      argument=[
        P('Quantitative workload is how much there is to do; qualitative workload is how difficult it is. They have different consequences and are frequently combined into one score.',
          '数量型负荷指"要做多少"，质量型负荷指"有多难"。二者后果不同，却常被合并为一个分数。'),
        P('In the job demands framework it is the archetypal demand: it consumes energy through the health-impairment path and predicts exhaustion more consistently than almost any other job characteristic.',
          '在工作要求框架中它是最典型的要求：通过健康损耗路径消耗能量，对耗竭的预测比几乎任何其他工作特征都更稳定。'),
        P('The challenge-hindrance distinction qualifies this: workload that is demanding but achievable can raise motivation, while workload experienced as obstructive only depletes.',
          '挑战—阻碍的区分对此加以限定：具有挑战性但可完成的负荷能提升动机，而被体验为阻碍的负荷只会消耗。'),
      ],
      development=[
        P('Objective workload measures from operational systems became available, which allows the perceptual measure to be validated rather than assumed.',
          '来自运营系统的客观负荷指标已可获得，这使感知测量可以被验证而非被假定。'),
      ],
      debates=[
        Debate('Is workload a challenge or a hindrance demand?', '工作负荷是挑战型还是阻碍型要求？',
               [Pos('Challenge position',
                    'High but achievable workload predicts engagement as well as strain, so classifying it as purely harmful misses half the effect.',
                    '高但可完成的负荷既预测紧张也预测投入；把它单纯归为有害，会漏掉一半效应。'),
                Pos('Hindrance position',
                    'Above a threshold the motivational path disappears and only depletion remains, so the challenge framing applies over a narrow range.',
                    '超过某个阈值后动机路径消失、只剩消耗；因此挑战性框定只在狭窄区间内成立。')],
               'Both supported at different levels, which means the linear specification most studies use is misspecified.',
               '在不同水平上各自成立——这意味着多数研究采用的线性设定是错的。'),
      ],
      theoretical=[
        P('The relationship with outcomes is probably curvilinear, but almost all studies fit a linear term and report an average slope that describes neither end.',
          '它与结果的关系很可能是曲线的，而几乎所有研究都拟合线性项，报告一个两端都不描述的平均斜率。'),
        P('Perceived workload confounds the demand with the person capacity to meet it, so the same objective load registers differently by experience and skill.',
          '感知负荷把"要求"与"个体应对能力"混在一起，因此同样的客观负荷会因经验与技能而记录不同。'),
      ],
      empirical=[
        P('Workload and strain are measured in the same self-report instrument, and a strained respondent reports higher workload, which inflates the relationship in both directions.',
          '负荷与紧张在同一份自评工具中测量，而处于紧张状态的受访者会报告更高负荷，这使二者关系在两个方向上都被抬高。'),
        P('Objective and perceived workload correlate only moderately, so a redesign that reduces the former may not reduce the latter.',
          '客观负荷与感知负荷只是中等相关，因此降低前者的再设计未必降低后者。'),
      ],
      temporal=[
        P('The measure assumes work has a countable volume within a bounded period. Where work is interrupt-driven and boundaries are porous, the load that matters is fragmentation and switching cost, which a quantity-and-pace scale does not ask about.',
          '该指标假定工作在有界时段内具有可计数的量。当工作由中断驱动、边界渗透时，真正重要的负荷是碎片化与切换成本，而"数量与节奏"量表并不询问这些。'),
        P('Where a system allocates tasks continuously, workload is set externally and can be adjusted faster than a person adapts, so it becomes a condition imposed rather than a characteristic of a job the person holds.',
          '当系统持续分配任务时，工作负荷由外部设定、且调整速度快于个体适应，它因而成为被施加的条件，而非个体所任岗位的特征。'),
      ],
      today=[
        P('Test for curvilinearity rather than assuming a linear demand, and separate quantitative from qualitative workload.',
          '应检验曲线关系而非假定线性要求，并把数量型与质量型负荷分开。'),
        P('Where operational data exist, measure objective load independently and report its correlation with the perceptual measure.',
          '当存在运营数据时，应独立测量客观负荷，并报告它与感知测量的相关。'),
      ]),

    # ------------------------------------------------------- network centrality
    D('network-centrality',
      era='Formalized in the 1970s; measures multiplied and their interpretation diverged as network data became abundant.',
      era_zh='1970 年代形式化；随着网络数据变得充裕，指标不断增多而解读日益分化。',
      situation=[
        P('Network research needed to say what a position is worth. Describing a structure was possible, but comparing actors within it required a number.',
          '网络研究需要说明"一个位置值多少"。描述结构是可行的，但要在结构内部比较行动者就需要一个数字。'),
        P('Centrality supplied it, but immediately raised the question of which centrality, since prominence can mean activity, brokerage, or connection to well-connected others.',
          '中心度提供了这个数字，却立刻带出"哪一种中心度"的问题——因为"显要"可以指活跃度、中介性，或与高连接者相连。'),
      ],
      argument=[
        P('Degree counts ties and captures activity or access volume. Betweenness counts how often an actor lies on shortest paths and captures brokerage. Eigenvector weights ties by the centrality of who they connect to and captures influence through well-connected others.',
          '度中心度计数联结，刻画活跃度或接触量；中介中心度计数行动者位于最短路径上的频次，刻画中介性；特征向量中心度按所连接对象的中心度加权，刻画经由高连接者的影响力。'),
        P('These are different theoretical claims. A study predicting information novelty should use betweenness; one predicting exposure should use degree, and choosing without a reason invites reporting whichever correlates.',
          '这是不同的理论主张：预测信息新颖性应用中介中心度，预测暴露程度应用度中心度；无理由地选择，等于在挑选与结果相关的那一个来报告。'),
      ],
      development=[
        P('Weighted, directed, and temporal variants were developed, and the choice among them adds further researcher degrees of freedom that are rarely reported.',
          '加权、有向与时序变体相继出现，在它们之间的选择又增添了研究者自由度，而这些很少被报告。'),
      ],
      debates=[
        Debate('Does centrality cause outcomes or reflect them?', '中心度是导致结果，还是反映结果？',
               [Pos('Position position',
                    'Structural position confers information and control advantages independent of the actor attributes.',
                    '结构位置独立于行动者属性而赋予信息与控制优势。'),
                Pos('Selection critique',
                    'Capable and successful actors attract ties, so centrality is partly an outcome, and cross-sectional designs cannot separate the two.',
                    '有能力、成功的行动者会吸引联结，因此中心度部分是结果；横截面设计无法把二者分开。')],
               'The selection problem is well established and requires longitudinal or design-based identification that most studies lack.',
               '选择性问题已被充分确立，需要多数研究并不具备的纵向或设计式识别。'),
      ],
      theoretical=[
        P('Centrality is defined relative to a network whose boundary the researcher chose, so the same actor has different centrality under different reasonable boundary rules.',
          '中心度是相对于研究者划定边界的网络定义的；在不同但同样合理的边界规则下，同一行动者的中心度并不相同。'),
        P('High centrality carries costs — coordination load, exposure, obligation — that the construct treats as unambiguously advantageous.',
          '高中心度伴随代价——协调负担、暴露、义务——而该构念把它当作无条件的优势。'),
      ],
      empirical=[
        P('Missing ties bias every measure, and betweenness is the most sensitive while also being the most used. Coverage is rarely reported.',
          '遗漏联结会使每个指标产生偏倚，其中中介中心度最敏感、也最常被使用，而覆盖情况很少被报告。'),
        P('Centrality computed from a network and then entered into ordinary regression violates independence, and standard errors from such models are not interpretable.',
          '从网络计算出中心度再放入普通回归会违反独立性，这类模型的标准误无法解读。'),
      ],
      temporal=[
        P('The measures were developed for networks elicited by survey, where a tie meant a relationship the respondent affirmed. Digital-trace networks record contact, and applying a measure designed for affirmed relationships to logged interaction changes what the number means.',
          '这些指标是为问卷获取的网络开发的，那里的联结意味着受访者确认过的关系。数字痕迹网络记录的是接触；把为"确认过的关系"设计的指标套用于日志互动，数字的含义已经改变。'),
        P('Platform networks are shaped by recommendation. A tie may exist because a system suggested it, which makes centrality partly a measure of algorithmic exposure rather than of social position.',
          '平台网络受推荐机制塑造。某条联结的存在可能只是因为系统推荐了它，这使中心度部分成为对算法曝光的测量，而非社会位置的测量。'),
      ],
      today=[
        P('Choose the measure from the mechanism and say why. Reporting several centralities and discussing the significant one is a search rather than a test.',
          '应依据机制选择指标并说明理由。报告多个中心度却只讨论显著的那个，是搜索而非检验。'),
        P('Report the boundary rule and missing-tie coverage, and use a network-aware model rather than ordinary regression on derived measures.',
          '应报告边界规则与遗漏联结覆盖情况，并使用考虑网络依赖的模型，而非对派生指标做普通回归。'),
      ]),

    # ------------------------------------------------------- quality performance
    D('quality-performance',
      era='Central to operations research since the quality movement of the 1980s; measurement contested throughout.',
      era_zh='自 1980 年代质量运动以来是运营研究的核心，其测量始终存在争议。',
      situation=[
        P('Quality was treated as a cost: improving it meant more inspection and rework, so there was an optimal defect rate above zero. Competitive experience contradicted that, and firms improving quality reduced cost at the same time.',
          '质量此前被当作成本：改善质量意味着更多检验与返工，因而存在一个高于零的最优缺陷率。竞争实践与此相悖——改善质量的企业同时降低了成本。'),
        P('Explaining that required distinguishing quality of conformance, which is about consistency, from quality of design, which is about what the specification promises.',
          '要解释这一点，就必须区分符合性质量（关乎一致性）与设计质量（关乎规格所承诺的内容）。'),
      ],
      argument=[
        P('Conformance quality is the degree to which output consistently meets specification. Reducing variability lowers defects, rework, and the buffers that variability requires, which is how quality and cost improve together.',
          '符合性质量指产出持续满足规格的程度。降低波动性可减少缺陷、返工，以及波动性所需要的缓冲——这正是质量与成本同步改善的原因。'),
        P('Perceived quality is a different construct, held by the customer and shaped by expectations rather than by specification. A product can conform perfectly and be judged poor.',
          '感知质量是另一个构念，由顾客持有、由期望而非规格塑造。一个产品可以完全符合规格却被评价为差。'),
        P('The two diverge most where the specification itself is wrong, which conformance measurement cannot detect by construction.',
          '当规格本身就错了时，二者背离最大——而符合性测量在构造上无法发现这一点。'),
      ],
      development=[
        P('Measurement extended from defect rates to process capability indices and then to supply-network-level quality, where a firm output quality depends on suppliers it does not control.',
          '测量从缺陷率扩展到过程能力指数，再到供应网络层面的质量——企业的产出质量取决于它并不控制的供应商。'),
      ],
      debates=[
        Debate('Is quality free?', '质量是免费的吗？',
               [Pos('Improvement position',
                    'Prevention costs less than failure, so investing in conformance reduces total cost and the trade-off is illusory.',
                    '预防成本低于失败成本，因此投资于符合性会降低总成本，所谓取舍是幻觉。'),
                Pos('Diminishing-returns position',
                    'The relation holds from a low base; beyond a level, further conformance requires disproportionate investment and the trade-off returns.',
                    '该关系在低起点上成立；超过某个水平后，进一步提升符合性需要不成比例的投入，取舍重新出现。')],
               'Both hold over different ranges, and studies rarely state which range their sample occupies.',
               '两者在不同区间各自成立，而研究很少说明其样本位于哪个区间。'),
      ],
      theoretical=[
        P('Conformance and perceived quality are frequently combined into one measure although they have different antecedents and can move in opposite directions.',
          '符合性质量与感知质量常被合并为一个指标，尽管它们前因不同且可能反向变动。'),
        P('Quality is defined relative to a specification, and who sets the specification is outside the construct even though it determines what conformance means.',
          '质量是相对于规格定义的，而"谁来设定规格"在构念之外——尽管它决定了符合性意味着什么。'),
      ],
      empirical=[
        P('Defect data come from the firm own detection system, so measured quality partly reflects detection capability: better detection can look like worse quality.',
          '缺陷数据来自企业自身的检测系统，因此所测质量部分反映检测能力——检测更好可能看起来像质量更差。'),
        P('Survey-based quality measures are usually reported by a manager who also reports performance, which is the standard same-source problem.',
          '基于问卷的质量指标通常由同时报告绩效的管理者填写，这是标准的同源问题。'),
      ],
      temporal=[
        P('Conformance measurement assumes a stable specification and a repeatable process. Where output is a service or a model-generated result whose acceptable range is contested, conformance is not well defined and defect rate does not describe the failure that matters.',
          '符合性测量假定规格稳定、过程可重复。当产出是服务、或可接受范围本身有争议的模型生成结果时，符合性并未被良好定义，缺陷率也无法描述真正重要的失效。'),
        P('Quality problems increasingly originate several tiers upstream in a network the focal firm cannot inspect, so firm-level conformance data describe a decreasing share of the quality risk.',
          '质量问题日益源自焦点企业无法检视的上游数层网络，因此企业层面的符合性数据所描述的质量风险占比越来越小。'),
      ],
      today=[
        P('Say whether the measure is conformance or perception and do not combine them. They answer different questions and diverge exactly where the interesting cases are.',
          '应说明指标测的是符合性还是感知，且不要合并。二者回答不同问题，且恰在有意思的个案上背离。'),
        P('Report how defects are detected. A change in measured quality is often a change in the detection system.',
          '应报告缺陷如何被检测。所测质量的变化，往往只是检测系统的变化。'),
      ]),

    # ---------------------------------------------------- competitive advantage
    D('competitive-advantage',
      era='Central to strategy since the 1980s; definitional disputes unresolved and largely unacknowledged in applied work.',
      era_zh='自 1980 年代起是战略研究的核心；定义之争未决，且在应用研究中基本未被承认。',
      situation=[
        P('Strategy needed a dependent variable that was about competition rather than about accounting outcomes, since a firm can be profitable without any advantage over rivals and vice versa.',
          '战略研究需要一个关于"竞争"而非"会计结果"的因变量——企业可以在对手面前毫无优势却盈利，反之亦然。'),
        P('The concept supplied the vocabulary but not the operational definition, and the gap between the two has persisted for four decades.',
          '这一概念提供了词汇，却没有提供操作定义；二者之间的落差已持续四十年。'),
      ],
      argument=[
        P('Advantage exists when a firm creates more value than rivals in the same product market. Value created is the difference between what buyers are willing to pay and the opportunity cost of the resources used.',
          '当企业在同一产品市场中创造出高于对手的价值时，优势即存在。所创造的价值是买方支付意愿与所用资源机会成本之差。'),
        P('Value created and value captured are distinct. A firm can create more value than anyone and capture little of it, and only the second shows in performance.',
          '价值创造与价值获取是不同的。企业可以创造出最高的价值却只获取很少，而只有后者体现在绩效中。'),
        P('Sustained advantage requires that rivals cannot imitate or substitute the source, which is where the resource-based conditions enter and why they are not separable from this construct.',
          '持续优势要求对手无法模仿或替代其来源——资源基础观的条件正是在此进入，也因此与该构念不可分离。'),
      ],
      development=[
        P('Value-based strategy formalized created and captured value using cooperative game theory, which supplied definitions the earlier verbal treatments lacked.',
          '价值基础战略用合作博弈论把创造价值与获取价值形式化，提供了此前文字表述所缺的定义。'),
      ],
      debates=[
        Debate('Is advantage the same as superior performance?', '优势等同于卓越绩效吗？',
               [Pos('Equivalence practice',
                    'Advantage is unobservable, so persistent above-average performance is the workable indicator and is what studies use.',
                    '优势不可观察，因此持续高于平均的绩效是可行指标，也是研究实际使用的。'),
                Pos('Distinctness position',
                    'Performance depends on value captured, bargaining, and industry conditions; equating the two makes the central proposition of the field circular.',
                    '绩效取决于价值获取、议价与产业条件；把二者等同会使该领域的核心命题变成循环论证。')],
               'The critique is correct and the practice continues, which is the main reason findings in this area are hard to interpret.',
               '批评是对的，做法却在延续——这正是该领域结论难以解读的主要原因。'),
      ],
      theoretical=[
        P('Measuring advantage by performance makes the proposition that advantage produces performance unfalsifiable, and most empirical work does exactly this.',
          '用绩效测量优势，会使"优势带来绩效"这一命题不可证伪；而多数经验研究正是这样做的。'),
        P('Advantage is defined relative to a competitor set the researcher specifies, and results change with the definition of the market.',
          '优势是相对于研究者指定的竞争者集合定义的，结论随市场界定而改变。'),
      ],
      empirical=[
        P('Willingness to pay and opportunity cost are the theoretical primitives and are almost never measured, so studies substitute accounting ratios that reflect neither.',
          '支付意愿与机会成本是理论上的基本量，却几乎从不被测量；研究以既不反映前者也不反映后者的会计比率代替。'),
        P('Persistence of abnormal returns is used as evidence of sustained advantage, but persistence also arises from measurement error and from industry effects.',
          '异常收益的持续性被当作持续优势的证据，然而持续性同样可能源于测量误差与产业效应。'),
      ],
      temporal=[
        P('The concept assumes rivals competing in a definable product market. Where firms compete across shifting category boundaries and complement as much as they compete, the comparison set that gives advantage its meaning is unstable.',
          '该概念假定对手在可界定的产品市场中竞争。当企业跨越移动的类别边界竞争、且竞争与互补并存时，赋予优势以意义的比较集本身就不稳定。'),
        P('Value capture increasingly depends on position in an ecosystem rather than on the firm own resources, so a construct built around firm-level sources of advantage explains a shrinking part of the outcome.',
          '价值获取日益取决于在生态系统中的位置而非企业自身资源；因此围绕"企业层面优势来源"构建的构念，所解释的结果占比不断缩小。'),
      ],
      today=[
        P('Define the competitor set and say whether the measure is value created or value captured. Most disagreement in this literature is definitional rather than empirical.',
          '应界定竞争者集合，并说明指标测的是创造价值还是获取价值。这一文献中的多数分歧是定义性的而非经验性的。'),
        P('Avoid using performance as both the measure of advantage and the outcome. If that is unavoidable, say so rather than presenting the result as a test.',
          '应避免把绩效同时用作优势的测量与结果变量。若无法避免，应如实说明，而不是把结果呈现为一次检验。'),
      ]),

    # -------------------------------------------- information processing capacity
    D('information-processing-capacity',
      era='Rooted in bounded rationality and 1970s organizational design theory; revived by analytics research.',
      era_zh='源自有限理性与 1970 年代组织设计理论，因分析学研究而复兴。',
      situation=[
        P('Organizational design theory needed to explain why structures differ. The proposal was that organizations are information processing systems and structure is a response to how much information the task requires.',
          '组织设计理论需要解释结构为何不同。其主张是：组织是信息处理系统，结构是对"任务需要处理多少信息"的回应。'),
        P('That reframed coordination as a capacity problem: uncertainty raises the information that must be processed during execution, and structures either raise capacity or reduce the need.',
          '这把协调重述为能力问题：不确定性提高了执行中必须处理的信息量，而结构要么提高能力、要么降低需求。'),
      ],
      argument=[
        P('Uncertainty is the difference between the information required to perform a task and the information already possessed. The larger the gap, the more must be processed while the work is done.',
          '不确定性是"完成任务所需信息"与"已掌握信息"之差。差距越大，在工作进行中必须处理的信息就越多。'),
        P('Organizations respond in two ways: reduce the need for processing through slack resources or self-contained units, or raise capacity through vertical information systems and lateral relations.',
          '组织有两类应对：通过冗余资源或自足单元降低处理需求；或通过纵向信息系统与横向关系提高处理能力。'),
        P('Fit between requirement and capacity predicts performance, which makes this a contingency argument and subject to the same operationalization problem as contingency theory generally.',
          '需求与能力之间的匹配预测绩效——这使它成为权变论证，并因此面临与权变理论相同的操作化问题。'),
      ],
      development=[
        P('Analytics research revived the framework to argue that data and tools raise capacity, though the original argument locates capacity in structure rather than in technology.',
          '分析学研究复兴了该框架，主张数据与工具提高处理能力；不过原初论证把能力定位在结构而非技术上。'),
      ],
      debates=[
        Debate('Does technology raise capacity or requirement?', '技术提高的是处理能力还是处理需求？',
               [Pos('Capacity position',
                    'Analytics and automation process more information than people can, which directly relieves the constraint the theory identifies.',
                    '分析与自动化能处理超出人力的信息量，直接缓解了理论所指认的约束。'),
                Pos('Requirement position',
                    'More available information raises what is expected to be considered, so requirement grows with capacity and the gap does not close.',
                    '可得信息越多，被期待纳入考量的内容也越多；因此需求随能力增长，差距并未缩小。')],
               'Open and directly relevant to whether analytics investment improves decisions or merely raises the standard.',
               '未决，且直接关系到"分析投入是改善决策还是只是抬高了标准"。'),
      ],
      theoretical=[
        P('Capacity is defined by what an organization can process but measured by what it does process, which conflates the constraint with the choice.',
          '能力按"组织能处理什么"定义，却按"组织实际处理了什么"测量，这把约束与选择混为一谈。'),
        P('The framework treats information as homogeneous, so processing more of it is treated as better regardless of its relevance or reliability.',
          '框架把信息视为同质的，因而"处理得更多"被当作更好，而不论其相关性与可靠性。'),
      ],
      empirical=[
        P('Both requirement and capacity are typically measured perceptually by managers, so fit is a self-assessment rather than an observed correspondence.',
          '需求与能力通常都由管理者主观评定，因此"匹配"是一种自我评估，而非被观察到的对应关系。'),
        P('Studies rarely observe what information was actually used in a decision, which is the quantity the theory is about.',
          '研究很少观察决策中实际使用了哪些信息，而这恰恰是理论所关注的量。'),
      ],
      temporal=[
        P('The framework was built when information was scarce and processing it was the constraint. Where information is abundant, the binding constraint is attention and selection, and a theory about raising throughput does not address which information should be processed.',
          '框架建立于信息稀缺、处理信息构成约束的时期。当信息充裕时，真正的约束是注意力与筛选，而"提高吞吐量"的理论并不回答"应当处理哪些信息"。'),
        P('It assumed processing capacity resides in people and structures. Where models filter, summarize, and rank before a person sees anything, part of the processing happens outside the organization design the framework describes.',
          '它假定处理能力存在于人与结构之中。当模型在任何人看到之前就已完成筛选、摘要与排序时，部分处理发生在框架所描述的组织设计之外。'),
      ],
      today=[
        P('Distinguish capacity from selection. For contemporary questions the interesting variable is usually what gets attended to, not how much is processed.',
          '应区分处理能力与筛选。对当代问题而言，有意思的变量通常是"什么被关注"，而非"处理了多少"。'),
        P('Measure requirement independently of capacity; asking the same manager about both produces a fit score that cannot be wrong.',
          '应独立于能力来测量需求；向同一位管理者询问两者，得到的匹配分数不可能出错。'),
      ]),

    # -------------------------------------------------------- demand uncertainty
    D('demand-uncertainty',
      era='Central to inventory and supply-chain research since the 1950s; the bullwhip literature reframed it from the 1990s.',
      era_zh='自 1950 年代起是库存与供应链研究的核心；1990 年代起牛鞭效应文献重新框定了它。',
      situation=[
        P('Inventory and capacity decisions depend on what demand will be. Treating demand as known produces policies that fail in exactly the conditions they were meant to handle.',
          '库存与产能决策取决于未来需求。把需求当作已知，会产生"恰恰在其本应应对的条件下失效"的策略。'),
        P('The construct makes the variability explicit so that safety stock, capacity buffers, and flexibility can be sized against it rather than guessed.',
          '该构念把波动性显式化，使安全库存、产能缓冲与柔性可以据之量化，而非靠猜测。'),
      ],
      argument=[
        P('Demand uncertainty covers volume, timing, and mix. These require different responses: volume uncertainty is buffered by stock, timing by capacity flexibility, and mix by postponement or commonality.',
          '需求不确定性涵盖数量、时点与组合。三者需要不同应对：数量不确定用库存缓冲，时点不确定用产能柔性，组合不确定用延迟差异化或零部件通用化。'),
        P('The critical insight from the bullwhip literature is that observed uncertainty upstream is partly manufactured by the ordering behaviour of downstream stages rather than by end-customer demand.',
          '牛鞭效应文献的关键洞见是：上游观察到的不确定性，有一部分是下游环节的订货行为制造出来的，而非来自终端顾客需求。'),
        P('That reframes the problem: some demand uncertainty is a property of the supply chain design and can be removed by sharing information, while the rest is genuinely exogenous.',
          '这重新框定了问题：部分需求不确定性是供应链设计的属性、可通过信息共享消除，其余部分才是真正外生的。'),
      ],
      development=[
        P('Information sharing, vendor-managed inventory, and collaborative forecasting were developed specifically to remove the manufactured component.',
          '信息共享、供应商管理库存与协同预测正是为消除"被制造出来的那部分"而发展的。'),
      ],
      debates=[
        Debate('Is demand uncertainty exogenous?', '需求不确定性是外生的吗？',
               [Pos('Exogenous position',
                    'End-customer demand is driven by factors outside the chain, and the firm task is to buffer against it.',
                    '终端需求由链条之外的因素驱动，企业的任务是对其加以缓冲。'),
                Pos('Endogenous position',
                    'Much observed variability is created by batching, promotions, and rationing inside the chain, and treating it as exogenous justifies buffers instead of fixing the cause.',
                    '大量观察到的波动由链条内部的批量订货、促销与配给制造；把它当作外生，等于用缓冲取代对成因的修正。')],
               'Both components exist, and separating them is what distinguishes a diagnostic study from a descriptive one.',
               '两种成分都存在；能否把它们分开，正是诊断性研究与描述性研究的区别。'),
      ],
      theoretical=[
        P('Uncertainty is usually operationalized as variance, which treats a predictable seasonal swing and an unforecastable shock as the same quantity although they call for opposite responses.',
          '不确定性通常被操作化为方差，这把"可预测的季节波动"与"无法预测的冲击"当作同一个量——而二者需要相反的应对。'),
        P('The firm own actions — pricing, promotion, assortment — generate part of the demand variability the model treats as external.',
          '企业自身的行为——定价、促销、品类组合——制造了模型视为外部的那部分需求波动。'),
      ],
      empirical=[
        P('Demand is measured by shipments or orders rather than by end-customer demand, so the measure already contains the bullwhip distortion the analysis should separate.',
          '需求以发货量或订单量测量而非终端需求，因此该指标本身已包含分析本应分离出去的牛鞭失真。'),
        P('Stockouts censor the record: unmet demand is not observed, so measured variability understates true variability in exactly the periods that matter.',
          '缺货会截断记录：未被满足的需求不被观察，因此所测波动恰在关键时期低估了真实波动。'),
      ],
      temporal=[
        P('Classical treatments assume a stationary demand distribution that can be estimated from history. Where demand is shaped by recommendation, promotion timing, and rapid product turnover, the distribution is non-stationary and history-based estimates are systematically wrong.',
          '经典处理假定需求分布平稳、可由历史估计。当需求受推荐、促销时点与产品快速更迭塑造时，分布是非平稳的，基于历史的估计系统性地出错。'),
        P('Point-of-sale visibility now makes the endogenous component removable in principle, so a study that measures uncertainty from orders without checking whether end demand data were available is describing a design choice rather than a condition.',
          '销售终端可见性如今在原则上使内生成分可被消除；因此仅从订单测量不确定性、而不核查是否可获得终端需求数据的研究，描述的是一项设计选择而非客观条件。'),
      ],
      today=[
        P('Separate forecastable variation from genuine uncertainty, and separate end-customer demand from order variability where the data allow.',
          '应把可预测的变异与真正的不确定性分开，并在数据允许时把终端需求与订单波动分开。'),
        P('Correct for censoring before estimating the demand distribution. Fitting to shipments reproduces the stockouts that shaped them.',
          '在估计需求分布之前应校正截断。对发货量拟合，只会复制塑造了这些数据的缺货。'),
      ]),
])
