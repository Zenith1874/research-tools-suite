# -*- coding: utf-8 -*-
"""Deep dives for catalog constructs, batch 3.

Operations and supply-chain constructs that appear heavily in the corpus, plus
two OB constructs whose measurement problems are worth stating explicitly.

Schema helpers live in ``research_catalog_deep_dives``.
"""

from research_catalog_deep_dives import D, Debate, P, Pos

CONSTRUCT_DIVES_B3 = dict([

    # -------------------------------------------- supplier relationship quality
    D('supplier-relationship-quality',
      era='Developed from relational exchange research in the 1990s; central to supply-chain research from the 2000s.',
      era_zh='1990 年代由关系型交换研究发展而来，2000 年代起成为供应链研究的核心构念。',
      situation=[
        P('Transaction cost economics explained buyer-supplier governance as a choice between market and hierarchy driven by safeguarding against opportunism. That framing predicted contracts and ownership but could not explain durable cooperative relationships that outperformed both.',
          '交易成本经济学把买方—供应商治理解释为市场与科层之间的选择，其驱动力是防范机会主义。这一框定能预测契约与所有权，却解释不了那些表现优于二者的持久合作关系。'),
        P('Relational exchange research argued that trust and norms can substitute for formal safeguards and enable investments that contracts cannot protect, and relationship quality names what such a relationship has more of.',
          '关系型交换研究主张信任与规范可以替代正式保障，使契约无法保护的投资成为可能；"关系质量"正是命名这类关系"多出来的东西"。'),
      ],
      argument=[
        P('The construct is multidimensional, typically combining trust in the partner, commitment to continuing the relationship, communication quality, and cooperative behaviour. It is a property of the dyad rather than of either firm.',
          '该构念是多维的，通常包含对伙伴的信任、维系关系的承诺、沟通质量与合作行为。它是二元关系的属性，而非任一方企业的属性。'),
        P('The prediction is that higher quality relationships support relationship-specific investment, faster joint problem solving, and better performance under disruption, because the parties can rely on adjustment rather than on renegotiation.',
          '预测是：更高质量的关系支持关系专用性投资、更快的联合问题解决，以及在中断情形下更好的表现——因为双方可以依靠调整而非重新谈判。'),
      ],
      development=[
        P('Later work separated the calculative and relational bases of trust, since a partner trusted because switching is expensive behaves differently from one trusted because of demonstrated goodwill.',
          '后续研究区分了信任的计算性基础与关系性基础：因转换成本高而被信任的伙伴，与因展现善意而被信任的伙伴，行为方式并不相同。'),
      ],
      debates=[
        Debate('Do formal contracts and relational governance substitute or complement?', '正式契约与关系治理是替代还是互补？',
               [Pos('Substitution position',
                    'Detailed contracts signal distrust and crowd out the relational norms that make flexible adjustment possible.',
                    '细致的契约释放不信任信号，会挤出使灵活调整成为可能的关系规范。'),
                Pos('Complementarity position',
                    'Contracts handle foreseeable contingencies and free the relationship to deal with the unforeseeable, so the two reinforce each other.',
                    '契约处理可预见的情形，从而让关系去应对不可预见的部分，二者相互强化。')],
               'Evidence favours complementarity in most settings, but the substitution effect appears where contracting is unusually detailed or adversarial.',
               '多数情境中证据支持互补，但当缔约异常细致或带有对抗性时，替代效应会出现。'),
      ],
      theoretical=[
        P('Combining trust, commitment, communication, and cooperation into one score assumes they move together; a relationship can have high trust and poor communication, and the composite hides that.',
          '把信任、承诺、沟通与合作合成一个分数，假定了它们同向变动；而一段关系可以信任度高却沟通很差，合成分掩盖了这一点。'),
        P('Quality is treated as good for both parties, though a strong relationship also raises switching costs and can lock a buyer into a supplier that has stopped being competitive.',
          '关系质量被视为对双方都好，然而牢固的关系同时抬高转换成本，可能把买方锁定在已失去竞争力的供应商身上。'),
      ],
      empirical=[
        P('Almost all evidence comes from one side of the dyad, usually the buyer, and buyer and supplier assessments of the same relationship diverge substantially.',
          '几乎全部证据都来自二元关系的一侧，通常是买方；而买卖双方对同一关系的评价差异很大。'),
        P('Relationship quality and performance are measured in the same survey by the same respondent, so a satisfied manager may be reporting both.',
          '关系质量与绩效由同一受访者在同一份问卷中测量，因此一位满意的经理可能只是同时报告了两者。'),
      ],
      temporal=[
        P('The construct assumes a relationship between two identifiable firms with named counterparts who accumulate history. Where sourcing runs through platforms, marketplaces, and frequently re-tendered contracts, there may be no counterpart to build quality with, and the mechanism has nothing to operate on.',
          '该构念假定关系存在于两家可辨识的企业之间，双方有具名对接人并积累历史。当采购经由平台、市场与频繁重新招标进行时，可能根本没有可建立关系质量的对象，机制也就无从作用。'),
        P('It was developed when disruptions were local and adjustment was bilateral. Multi-tier disruptions propagate through suppliers a firm has no relationship with, and dyadic relationship quality does not reach them.',
          '它发展于中断是局部的、调整是双边的时期。多层级中断经由企业毫无关系的供应商传导，而二元关系质量触及不到那里。'),
      ],
      today=[
        P('Collect both sides where possible and report the divergence. The gap between buyer and supplier assessments is often the substantive finding.',
          '尽可能收集双方数据并报告分歧。买卖双方评价之间的落差，往往才是实质性发现。'),
        P('If the question is about disruption, specify the tier. Relationship quality with a direct supplier says little about a failure two tiers upstream.',
          '若问题关乎中断，应指明层级。与直接供应商的关系质量，对上游两级的失效几乎没有说明力。'),
      ]),

    # ---------------------------------------------------- supply chain resilience
    D('supply-chain-resilience',
      era='Emerged after the disruptions of the early 2000s; measurement debated throughout, and attention intensified sharply after 2020.',
      era_zh='2000 年代初的中断事件后兴起，测量始终存在争议，2020 年后关注度急剧上升。',
      situation=[
        P('Supply chain research had optimized for efficiency: lean inventory, single sourcing, and long lead times were rational under stable demand and reliable transport.',
          '供应链研究长期以效率为优化目标：精益库存、单一供应商与长提前期，在需求稳定、运输可靠的条件下都是理性的。'),
        P('A series of disruptions showed those choices had removed the buffers that absorb shocks, and the field needed a construct for the capability that efficiency had been trading away.',
          '一系列中断事件表明，这些选择消除了吸收冲击的缓冲；该领域因而需要一个构念来指称"被效率换掉的那种能力"。'),
      ],
      argument=[
        P('Resilience is usually decomposed into phases: readiness before a disruption, response during it, recovery afterwards, and adaptation that changes the system for the next one.',
          '韧性通常按阶段分解：中断前的准备、中断中的响应、事后的恢复，以及为下一次而改变系统的适应。'),
        P('The phases have different antecedents. Readiness comes from visibility and redundancy; response from flexibility and decision speed; recovery from resources and relationships; adaptation from learning. Treating them as one capability obscures which is missing.',
          '各阶段前因不同：准备来自可见性与冗余；响应来自柔性与决策速度；恢复来自资源与关系；适应来自学习。把它们当作单一能力，会掩盖究竟缺的是哪一环。'),
        P('The central tension is with efficiency. Redundancy and flexibility cost money that shows on the income statement, while the benefit appears only in states of the world that may not occur.',
          '核心张力在于与效率的冲突。冗余与柔性的成本会体现在利润表上，而收益只在可能不会发生的世界状态中显现。'),
      ],
      development=[
        P('Attention moved from firm-level buffers to network structure, on the argument that resilience is a property of the network and cannot be secured by any single firm acting alone.',
          '关注点从企业层面的缓冲转向网络结构，理由是韧性是网络的属性，任何单一企业单独行动都无法确保它。'),
      ],
      debates=[
        Debate('Can resilience be measured before a disruption?', '中断发生之前能测量韧性吗？',
               [Pos('Capability position',
                    'Resilience is a latent capability that can be assessed through its antecedents — visibility, redundancy, flexibility — without waiting for a shock.',
                    '韧性是潜在能力，可通过其前因——可见性、冗余、柔性——加以评估，无需等待冲击发生。'),
                Pos('Outcome position',
                    'Only observed performance under disruption reveals it, and firms that scored well on capability measures frequently failed when tested.',
                    '只有中断中的实际表现才能揭示它；在能力指标上得分高的企业，实际受考验时经常失败。')],
               'Open, and it is the central measurement problem in this literature.',
               '未决，这是该文献的核心测量问题。'),
      ],
      theoretical=[
        P('Resilience, robustness, agility, and flexibility are used with overlapping meanings, and studies claiming the same construct frequently measure different things.',
          '韧性、稳健性、敏捷性与柔性的用法相互重叠，自称测量同一构念的研究常常测的是不同东西。'),
        P('It is defined relative to a disruption type. Resilience to a demand shock and to a supplier failure require different capabilities, and a general score assumes they are the same.',
          '它是相对于某类中断定义的。应对需求冲击与应对供应商失效所需的能力不同，而通用分数假定二者相同。'),
      ],
      empirical=[
        P('Most evidence is retrospective survey data collected after a disruption, when respondents know the outcome and reconstruct their preparedness accordingly.',
          '多数证据是中断之后收集的回溯性问卷数据；此时受访者已知结果，并据此重构自己当初的准备程度。'),
        P('Survivorship is severe: firms that failed are not available to be surveyed, which biases estimates of what resilience requires.',
          '存活偏差严重：失败的企业无法被调查，这使"韧性需要什么"的估计产生偏倚。'),
      ],
      temporal=[
        P('The construct was built around discrete, locatable disruptions — a fire, a port closure, a supplier bankruptcy — with a clear before and after. Prolonged and overlapping disruptions have no recovery phase to measure, and the phase model that organizes the construct does not describe them.',
          '该构念围绕离散、可定位的中断构建——一场火灾、一次港口关闭、一家供应商破产——有清晰的前后之分。长期且相互叠加的中断没有可测量的恢复阶段，组织该构念的阶段模型无法描述它们。'),
        P('Visibility was theorized as knowing your suppliers. Where risk originates two or three tiers upstream in firms the buyer cannot name, visibility as originally conceived is not achievable and the antecedent cannot be measured as specified.',
          '可见性被设想为"了解你的供应商"。当风险源自买方无法指名的上游二三级企业时，原初设想的可见性无法实现，该前因也就无法按其定义被测量。'),
      ],
      today=[
        P('Name the disruption type and the phase. A general resilience score answers no specific question and cannot be compared across studies.',
          '应指明中断类型与阶段。通用韧性分数不回答任何具体问题，也无法跨研究比较。'),
        P('Where possible use observed performance during an actual disruption rather than a preparedness survey, and report which firms are missing from the sample.',
          '尽可能使用真实中断期间的实际表现，而非准备度问卷，并报告样本中缺失了哪些企业。'),
      ]),

    # ------------------------------------------------------- process performance
    D('process-performance',
      era='Rooted in industrial engineering; formalized for research through operations management from the 1980s.',
      era_zh='源自工业工程，1980 年代起经由运营管理形式化为研究构念。',
      situation=[
        P('Firm-level performance measures are too aggregated to evaluate an operational change: a process improvement can be real and still invisible in annual profit, which is affected by everything else the firm does.',
          '企业层面的绩效指标过于聚合，无法评估一项运营改进：流程改善可能是真实的，却在受企业其他一切影响的年度利润中不可见。'),
        P('Operations research needed an outcome measured at the level where the intervention acts, which is the process itself.',
          '运营研究需要在"干预实际作用的层面"上测量结果，而那个层面就是流程本身。'),
      ],
      argument=[
        P('The construct is normally decomposed into throughput, cycle time, quality or reliability, and cost. These trade off against one another, which is the substance of most operational decisions.',
          '该构念通常分解为吞吐量、周期时间、质量或可靠性，以及成本。它们彼此存在取舍，而这正是多数运营决策的实质。'),
        P('Because the dimensions trade off, a single composite score can hide the decision that was actually made. Reporting an improvement without saying what was given up is the most common way this construct is misused.',
          '由于各维度相互取舍，单一合成分数会掩盖真正作出的决策。报告改进而不说明放弃了什么，是该构念最常见的误用方式。'),
      ],
      development=[
        P('Balanced measurement frameworks were introduced precisely to prevent optimization of one dimension at the expense of the others, which is what single-metric management produces.',
          '平衡式测量框架的引入，正是为了防止以牺牲其他维度为代价优化单一维度——而这正是单指标管理所导致的结果。'),
      ],
      debates=[
        Debate('Is process improvement visible at the firm level?', '流程改进在企业层面可见吗？',
               [Pos('Aggregation position',
                    'Real operational gains should eventually appear in financial performance; if they never do, the improvement was local or offset elsewhere.',
                    '真实的运营收益最终应体现在财务绩效中；若始终不出现，说明改进只是局部的或被别处抵消了。'),
                Pos('Measurement position',
                    'Firm performance is affected by too many factors for a process gain to be detectable, so absence of a financial effect is not evidence of no effect.',
                    '企业绩效受太多因素影响，流程收益难以被检测；因此没有财务效应并不构成"无效应"的证据。')],
               'Both are partly right; the practical implication is to measure at the process level and treat firm-level effects as a separate question.',
               '两者都部分正确；实践含义是在流程层面测量，并把企业层面效应当作另一个问题处理。'),
      ],
      theoretical=[
        P('Process boundaries are a researcher decision. Where the process starts and ends determines what counts as cycle time, and comparisons across studies frequently draw the boundary differently.',
          '流程边界由研究者决定。流程从哪里开始、到哪里结束，决定了什么算作周期时间；跨研究比较时边界划法常常不同。'),
        P('Efficiency and reliability are treated as jointly desirable, but the buffers that produce reliability are exactly what efficiency removes.',
          '效率与可靠性被视为可兼得，但产生可靠性的缓冲，恰恰是效率所要去除的东西。'),
      ],
      empirical=[
        P('Operational data are often supplied by the organization being studied, which selects what to share and has an interest in the result.',
          '运营数据常由被研究组织提供，而它会挑选分享什么，并对结论有利害关系。'),
        P('Improvement studies rarely have a comparison process, so a gain can reflect learning, attention, or demand conditions rather than the intervention.',
          '改进研究很少设有对照流程，因此收益可能来自学习、关注度或需求条件，而非干预本身。'),
      ],
      temporal=[
        P('The measurement tradition assumes a repeatable process with countable units and a stable definition of a completed cycle. Service, knowledge, and platform-mediated work often lack a discrete unit, and applying throughput and cycle-time logic to them measures what is countable rather than what matters.',
          '这一测量传统假定流程可重复、单位可计数、"一次完整循环"的定义稳定。服务、知识与平台中介的工作往往缺少离散单位，把吞吐量与周期时间逻辑套用其上，测到的是"可计数之物"而非"重要之物"。'),
        P('Instrumentation changed what is observable. Where every step is logged automatically, process data are abundant but reflect what the system records; steps performed outside the system are invisible and can absorb the work that the measured improvement displaced.',
          '仪表化改变了可观察的内容。当每一步都被自动记录时，流程数据充裕，却只反映系统所记录的部分；在系统之外完成的步骤不可见，而它们可能吸收了被"改进"挤出去的工作。'),
      ],
      today=[
        P('Report the dimensions separately and state the trade-off. An improvement in one dimension with no account of the others is an incomplete finding.',
          '应分别报告各维度并说明取舍。只报告一个维度的改善而不交代其他维度，是不完整的发现。'),
        P('Define the process boundary explicitly, and check whether displaced work reappears outside it.',
          '应明确界定流程边界，并检查被挤出的工作是否在边界之外重新出现。'),
      ]),

    # ------------------------------------------------------ turnover intention
    D('turnover-intention',
      era='Standard proxy for turnover since the 1970s; the intention-behaviour gap documented consistently since.',
      era_zh='自 1970 年代起成为离职行为的标准代理，其与实际行为的落差此后被持续记录。',
      situation=[
        P('Turnover is expensive to study directly: it requires following people over time, and by the time someone leaves the organization they are hard to survey.',
          '直接研究离职代价高昂：需要长期追踪个体，而当一个人离开组织时，又难以再对他施测。'),
        P('Intention was adopted as the practical substitute, on the reasoning that intention is the immediate antecedent of the behaviour and can be measured in a single cross-sectional survey.',
          '意向因而被作为务实替代物，其理由是：意向是行为的近端前因，且可在一次横截面问卷中测得。'),
      ],
      argument=[
        P('The construct asks how likely a person is to leave within a stated horizon. It is deliberately narrow, and its value depends entirely on the strength of the intention-behaviour link.',
          '该构念询问个体在特定时间范围内离职的可能性。它被刻意设计得狭窄，其价值完全取决于意向与行为之间联系的强度。'),
        P('That link is real but far from perfect. Intention predicts turnover better than satisfaction or commitment do, and considerably worse than the substitution practice implies.',
          '这一联系真实存在但远非完美：意向对离职的预测优于满意度与承诺，却明显弱于"以意向替代行为"这一做法所暗示的程度。'),
      ],
      development=[
        P('Job embeddedness was developed partly in response, arguing that what keeps people is links, fit, and sacrifice rather than the absence of an intention to leave.',
          '工作嵌入理论的提出部分正是对此的回应：留住人的是联结、匹配与牺牲，而非"没有离职意向"。'),
      ],
      debates=[
        Debate('Is intention an acceptable substitute for turnover?', '意向能作为离职行为的可接受替代吗？',
               [Pos('Practical position',
                    'Intention is the strongest available single predictor and makes research feasible where following leavers is not.',
                    '意向是现有最强的单一预测变量，使"无法追踪离职者"的研究成为可能。'),
                Pos('Critical position',
                    'The gap is large and systematic: labour market conditions, alternatives, and constraints determine whether an intention becomes a departure, and none of them is in the construct.',
                    '这一落差既大且系统：劳动力市场状况、替代机会与约束条件决定意向是否变成离职，而它们都不在该构念之内。')],
               'Open in practice. The gap is well documented and the substitution continues because the alternative is expensive.',
               '实践中未决。落差有充分记录，替代做法仍在延续，因为替代方案成本高昂。'),
      ],
      theoretical=[
        P('Intention conflates wanting to leave with expecting to leave. A person can want to leave with no prospect of doing so, and the standard scale does not separate the two.',
          '意向把"想离开"与"预期会离开"混在一起。一个人可以很想走却毫无可能，而标准量表并不区分二者。'),
        P('The construct treats leaving as a single event, though voluntary, involuntary, and functional turnover have different antecedents and different consequences for the organization.',
          '该构念把离职当作单一事件，然而主动离职、被动离职与功能性离职的前因不同，对组织的后果也不同。'),
      ],
      empirical=[
        P('Intention and its predictors are measured in the same survey, so the model explains an attitude with other attitudes collected at the same moment.',
          '意向与其预测变量在同一份问卷中测量，因此模型是用同一时点收集的其他态度来解释一种态度。'),
        P('Studies that do follow up frequently find that a substantial share of those with high intention stay and some with low intention leave, which the cross-sectional design cannot see.',
          '有跟踪的研究常发现：高意向者中相当一部分留下，低意向者中也有人离开——这是横截面设计看不见的。'),
      ],
      temporal=[
        P('The construct assumes leaving means exiting the organization for another employer. Internal mobility, contract work, and portfolio careers make the boundary being crossed less clear, and a respondent may answer about leaving a role rather than the organization.',
          '该构念假定"离开"意味着离开组织去往另一雇主。内部流动、合约用工与组合式职业使被跨越的边界不再清晰，受访者回答的可能是离开某个岗位而非组织。'),
        P('It was validated in labour markets where switching was costly and infrequent. Where hiring is faster and search is continuous, the interval between intention and action shortens, which changes what a stated horizon means.',
          '它是在"转换成本高、频率低"的劳动力市场中完成验证的。当招聘更快、求职持续进行时，意向与行动之间的间隔缩短，"特定时间范围"的含义随之改变。'),
      ],
      today=[
        P('If actual turnover can be observed, use it. Where intention must be used, say so explicitly and do not describe the finding as being about turnover.',
          '若能观察到实际离职就应使用它。必须使用意向时应明确说明，且不要把发现描述为关于"离职"的。'),
        P('Measure labour market alternatives alongside intention. Without them the model cannot distinguish someone who will leave from someone who merely wants to.',
          '应在测量意向的同时测量劳动力市场替代机会。缺少它，模型无法区分"将要离开的人"与"只是想离开的人"。'),
      ]),

    # ------------------------------------------------------ psychological safety
    D('psychological-safety',
      era='Named in 1999 for team learning research; widely popularized from the 2010s and applied well beyond its original scope.',
      era_zh='1999 年为团队学习研究提出，2010 年代起被广泛普及，应用范围远超其最初界定。',
      situation=[
        P('Team learning research faced a puzzle: teams that made more errors sometimes performed better. The resolution was that they were not making more errors but reporting more of them.',
          '团队学习研究曾面临一个悖论：错误更多的团队有时表现更好。答案是：它们并非犯了更多错误，而是报告了更多错误。'),
        P('That required a construct for the condition under which people are willing to admit a mistake, ask a question, or raise a concern — something distinct from cohesion or trust in a specific person.',
          '这需要一个构念来指称"人们愿意承认错误、提出疑问、表达顾虑"的条件——它有别于凝聚力，也有别于对某个具体个人的信任。'),
      ],
      argument=[
        P('Psychological safety is a shared belief that the team is safe for interpersonal risk taking. It is about the group climate, not about an individual disposition or a dyadic relationship.',
          '心理安全感是"本团队适于承担人际风险"的共享信念。它关乎群体氛围，而非个体特质或二元关系。'),
        P('The mechanism is specific: it lowers the perceived cost of speaking up, which enables error reporting, question asking, and boundary spanning — the behaviours through which a team learns.',
          '其机制是具体的：它降低了发声的感知成本，从而促成错误报告、提问与跨界沟通——团队正是经由这些行为学习的。'),
        P('It is not comfort, niceness, or lowered standards. The original formulation pairs it with accountability: safety without demanding standards produces complacency rather than learning.',
          '它不是舒适、和气或降低标准。原初表述把它与问责并置：没有高标准要求的安全感只会产生自满，而非学习。'),
      ],
      development=[
        P('Applications extended it from teams to organizations and to individual-level outcomes, which stretched a group-level climate construct beyond the level at which it was defined.',
          '应用把它从团队扩展到组织乃至个体层面的结果，这使一个群体层面的氛围构念被拉伸到超出其定义层面的范围。'),
      ],
      debates=[
        Debate('Is psychological safety a group or an individual property?', '心理安全感是群体属性还是个体属性？',
               [Pos('Climate position',
                    'It is defined as a shared belief; aggregation requires demonstrated agreement within the team, and without agreement the construct is not present.',
                    '它被定义为共享信念；聚合必须以团队内部的一致性为前提，缺乏一致性时该构念并不成立。'),
                Pos('Individual position',
                    'Perceptions differ systematically within teams — by tenure, status, and demographic position — and averaging them erases exactly the variation that matters.',
                    '团队内部的感知存在系统性差异——因任期、地位与人口特征而异——把它们平均掉，恰恰抹去了最重要的那部分变异。')],
               'Increasingly settled toward measuring both: the team mean and the within-team variation carry different information.',
               '越来越倾向于两者都测：团队均值与团队内差异承载不同信息。'),
      ],
      theoretical=[
        P('The pairing with accountability is frequently dropped in application, which turns a learning construct into a comfort construct and changes what an intervention would target.',
          '与问责的并置在应用中常被丢弃，这把一个关于学习的构念变成了关于舒适的构念，也改变了干预应当针对什么。'),
        P('Safety is treated as uniformly distributed within a team, though the people most at risk from speaking up are usually the ones with least standing.',
          '安全感被视为在团队内部均匀分布，然而发声风险最大的，通常正是地位最低的人。'),
      ],
      empirical=[
        P('The scale is short and widely used, which is why it travels well, but aggregation to team level often proceeds without reporting the agreement statistics that justify it.',
          '该量表简短、使用广泛，因而易于迁移；但聚合到团队层面时，常常不报告为其提供正当性的一致性统计量。'),
        P('Safety and the learning behaviours it predicts are usually rated by the same respondents at the same time, so the mechanism is established by association.',
          '安全感与它所预测的学习行为通常由同一批受访者在同一时点评定，因此机制只由关联确立。'),
      ],
      temporal=[
        P('The construct was developed for co-located teams where speaking up happened in a room and its cost was visible in real time. In distributed and asynchronous work, raising a concern is written, persistent, and searchable, which changes the risk being taken and may not be what the scale asks about.',
          '该构念是为同处一地的团队开发的：发声发生在同一个房间里，其代价是实时可见的。在分布式与异步工作中，提出顾虑是书面的、持久的、可检索的，所承担的风险已经不同，而量表所问的可能并非这种风险。'),
        P('It was defined before speech at work was routinely recorded. Where discussion happens on logged platforms that can be reviewed later, the perceived cost of interpersonal risk includes an audience the original formulation did not contemplate.',
          '它的界定早于"工作中的言论被例行记录"。当讨论发生在可被日后调阅的平台上时，人际风险的感知成本包含了原初表述未曾设想的受众。'),
      ],
      today=[
        P('Report team agreement before aggregating, and analyse the within-team variation. Who does not feel safe is usually the more consequential finding.',
          '聚合前应报告团队一致性，并分析团队内差异。谁感到不安全，往往是更有后果的发现。'),
        P('Keep accountability in the model. A study that finds safety without performance standards has found comfort, and should say so.',
          '应把问责保留在模型中。发现"有安全感而无绩效标准"的研究，找到的是舒适，理应如此表述。'),
      ]),
])
