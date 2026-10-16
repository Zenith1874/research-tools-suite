# -*- coding: utf-8 -*-
"""Deep dives for catalog constructs, batch 4: algorithmic work and adoption.

These five constructs describe the phenomena the workspace is most often used to
study, and they are the ones where the era-bound limitation section matters most
in reverse: unlike older constructs whose assumptions have expired, several of
these are so new that their measurement has not yet stabilized.

Schema helpers live in ``research_catalog_deep_dives``.
"""

from research_catalog_deep_dives import D, Debate, P, Pos

CONSTRUCT_DIVES_B4 = dict([

    # ------------------------------------------------------ algorithmic control
    D('algorithmic-control',
      era='Named in platform-labour research from around 2015; measurement still unsettled and largely qualitative.',
      era_zh='约 2015 年起在平台劳动研究中被命名，测量至今未定型，仍以质性为主。',
      situation=[
        P('Labour process research had a vocabulary for control: direct supervision, bureaucratic rules, and normative or cultural control. Platform work fitted none of them cleanly — nobody instructs the worker, yet behaviour is tightly shaped.',
          '劳动过程研究已有一套控制词汇：直接监督、科层规则、规范或文化控制。平台劳动与其中任何一种都不吻合——没有人下指令，行为却被紧密塑造。'),
        P('The gap was that control was being exercised through the allocation of work and the design of incentives rather than through instruction, and existing constructs had no way to name a supervisor that is a system.',
          '缺口在于：控制是经由任务分配与激励设计而非指令来施加的，而既有构念无法为"作为系统的主管"命名。'),
      ],
      argument=[
        P('Algorithmic control is direction, evaluation, and discipline carried out through an algorithmic system. The three functions map onto what a supervisor does, which is what makes the analogy useful and also what makes it partial.',
          '算法控制是经由算法系统实施的指派、评价与惩戒。这三项功能对应主管的职能——这既使类比有用，也使它并不完整。'),
        P('The distinctive features are that it is continuous rather than episodic, opaque rather than explainable, and enacted through what the worker is offered rather than through what they are told.',
          '其显著特征是：持续而非间歇、不透明而非可解释、并且通过"给员工什么机会"而非"告诉员工什么"来实施。'),
        P('It is analytically separable from monitoring. A system can observe extensively without directing, and can direct through allocation without observing much, and conflating the two is the most common error in this literature.',
          '它在分析上可与监控分离：系统可以广泛观察而不指派，也可以通过分配来指派而观察不多。把二者混为一谈是这一文献中最常见的错误。'),
      ],
      development=[
        P('Research extended from gig platforms to conventional employment, where scheduling, routing, and performance systems perform the same functions inside a firm that also has human managers.',
          '研究从零工平台扩展到常规雇佣：在同时拥有人类管理者的企业内部，排班、派单与绩效系统承担着同样的功能。'),
      ],
      debates=[
        Debate('Is algorithmic control a new form or an intensification of an old one?', '算法控制是新形态还是旧形态的强化？',
               [Pos('Novelty position',
                    'Continuous, opaque, and automatically enforced direction is different in kind: there is no supervisor to appeal to and no rule to read.',
                    '持续、不透明、自动执行的指派在性质上不同：没有可申诉的主管，也没有可阅读的规则。'),
                Pos('Continuity position',
                    'It is Taylorist measurement and bureaucratic rule applied with better instruments; treating it as new obscures a century of labour process research.',
                    '它只是以更好的工具实施的泰勒式测量与科层规则；把它当作全新事物，会遮蔽一个世纪的劳动过程研究。')],
               'Open, and it determines whether existing control constructs can be reused or new ones are required.',
               '未决，且它决定了既有控制构念能否复用，还是必须建立新构念。'),
      ],
      theoretical=[
        P('Control and monitoring are used interchangeably in much of the literature, which makes it impossible to tell whether an effect comes from being watched or from being directed.',
          '大量文献把控制与监控混用，因而无法判断某效应究竟来自"被观察"还是"被指派"。'),
        P('The construct is defined by the mechanism rather than the experience, so two systems with identical architecture can be experienced very differently depending on whether the worker can predict them.',
          '该构念以机制而非体验来定义，因此架构相同的两个系统，会因员工能否预测而带来截然不同的体验。'),
      ],
      empirical=[
        P('Most evidence is qualitative and drawn from a small number of well-studied platforms, so the empirical base is narrow relative to the generality of the claims made.',
          '多数证据是质性的，且取自少数被反复研究的平台；相对于其主张的普遍性，经验基础相当狭窄。'),
        P('Survey measures are emerging but are not yet comparable across studies, and several use items that would also be endorsed under ordinary close supervision.',
          '问卷量表正在出现，但尚不能跨研究比较；其中若干题项在普通的严密监督下同样会被认同。'),
      ],
      temporal=[
        P('The construct was built by studying platforms where the algorithm was fixed and adversarial, and workers developed folk theories to game it. Systems that adapt to individual behaviour, or that a worker can query in natural language, change both the opacity and the gaming dynamic that early accounts describe.',
          '该构念建立在对"算法固定且带对抗性、员工发展出民间理论加以博弈"的平台研究之上。会随个体行为自适应、或员工可用自然语言询问的系统，改变了早期研究所描述的不透明性与博弈动态。'),
        P('It was developed before regulation required explanation of automated decisions in some jurisdictions. Where a right to explanation exists, opacity is a legal variable rather than a fixed property, and comparisons across jurisdictions are not comparing the same construct.',
          '它发展于某些法域尚未要求解释自动化决策之前。当存在解释权时，不透明性是一个法律变量而非固定属性，跨法域比较所比的并非同一构念。'),
      ],
      today=[
        P('Separate control from monitoring in the design and say which one the argument is about. An effect attributed to control that comes from observation is a different finding.',
          '设计上应把控制与监控分开，并说明论证针对哪一个。把源自观察的效应归因于控制，是另一种发现。'),
        P('Describe the system: what it allocates, on what inputs, with what recourse. Without that a reader cannot tell whether two studies of algorithmic control studied the same thing.',
          '应描述该系统：分配什么、依据哪些输入、有何救济途径。缺少这些，读者无法判断两项"算法控制"研究研究的是否同一事物。'),
      ]),

    # --------------------------------------------------- algorithmic monitoring
    D('algorithmic-monitoring',
      era='Continuous with electronic performance monitoring research from the 1980s; renamed and re-theorized for algorithmic systems from the 2010s.',
      era_zh='与 1980 年代的电子绩效监控研究一脉相承，2010 年代为算法系统重新命名与理论化。',
      situation=[
        P('Electronic performance monitoring research had established that being watched changes behaviour, generally raising measured output on simple tasks while increasing stress and reducing quality on complex ones.',
          '电子绩效监控研究已确立：被观察会改变行为——在简单任务上通常提高可测产出，在复杂任务上则增加压力、降低质量。'),
        P('What changed was scale and inference. Monitoring moved from sampling specific behaviours to recording nearly everything, and from recording to inferring states the worker did not disclose.',
          '变化的是规模与推断。监控从"抽样特定行为"变为"几乎记录一切"，再从记录进一步走向"推断员工并未披露的状态"。'),
      ],
      argument=[
        P('The construct is the automated, continuous collection and evaluation of work activity data. Three properties do the theoretical work: comprehensiveness, immediacy of feedback, and the inferential step from observed behaviour to an unobserved attribute.',
          '该构念指对工作活动数据的自动化、持续采集与评估。三项属性承担理论重量：全面性、反馈的即时性，以及"从可观察行为推断不可观察属性"这一推断步骤。'),
        P('It is theorized primarily as a job demand: it consumes attention, constrains discretion, and raises the cost of any deviation, which is why it appears in strain models rather than only in performance models.',
          '它主要被理论化为一种工作要求：消耗注意力、限制裁量、抬高任何偏离的代价——因此它出现在紧张模型中，而不只是绩效模型中。'),
      ],
      development=[
        P('Attention moved from whether monitoring occurs to how it is framed. The same system presented as developmental feedback and as performance surveillance produces different reactions, which places purpose attribution at the centre.',
          '关注点从"是否存在监控"转向"如何被框定"。同一系统被呈现为发展性反馈还是绩效监视，会引发不同反应，这把"目的归因"置于核心位置。'),
      ],
      debates=[
        Debate('Is the effect driven by observation or by evaluation?', '效应由观察驱动还是由评价驱动？',
               [Pos('Observation position',
                    'Being watched alone changes behaviour regardless of consequence, which is the classic finding.',
                    '仅仅被观察就会改变行为，与后果无关——这是经典发现。'),
                Pos('Evaluation position',
                    'What matters is that the record is used to judge and allocate; monitoring with no consequence attached produces much weaker effects.',
                    '真正起作用的是记录被用于评判与分配；不附带后果的监控效应弱得多。')],
               'Open. Designs that vary consequence while holding observation constant are rare and would be highly informative.',
               '未决。在保持观察不变的同时改变后果的设计很少见，而这类设计会极有信息量。'),
      ],
      theoretical=[
        P('Monitoring is treated as a single construct, but comprehensiveness, transparency, and consequence are separable and probably have opposite effects on trust.',
          '监控被当作单一构念，但全面性、透明度与后果是可分离的，且很可能对信任产生相反影响。'),
        P('The inferential step — deriving engagement, risk, or intent from behavioural traces — is what workers object to most, and it is not represented in measures built for observation of behaviour.',
          '推断步骤——从行为痕迹推导投入度、风险或意图——是员工最反感之处，而为"行为观察"设计的量表并未表达这一点。'),
      ],
      empirical=[
        P('Field access is hard, so much evidence comes from vignettes and lab analogues where the monitoring has no real consequence, which is the condition the theory says matters most.',
          '进入现场困难，因此大量证据来自情境实验与实验室类比——其中监控并无真实后果，而理论恰恰认为后果最重要。'),
        P('Perceived and actual monitoring diverge substantially. Workers frequently misjudge what is recorded, and studies rarely measure both.',
          '感知监控与实际监控差异很大。员工常常误判什么被记录，而研究很少同时测量两者。'),
      ],
      temporal=[
        P('Instruments were written when monitoring meant a countable behavioural record — keystrokes, call duration, location. Systems that infer affect, attention, or collaboration quality from ambient data are monitoring something the worker cannot see being collected, and a scale asking about recorded activity will not register it.',
          '量表写于监控意味着"可计数行为记录"的时期——击键、通话时长、位置。从环境数据推断情绪、注意力或协作质量的系统，所监控的是员工看不到被采集的东西，而询问"活动是否被记录"的量表无法捕捉它。'),
        P('It was theorized when monitoring and the employment relationship were bundled. Where the monitoring runs on tools the worker also uses personally, or continues outside working hours, the boundary that made consent meaningful is no longer where the instrument assumes it is.',
          '它成形于监控与雇佣关系捆绑之时。当监控运行在员工也用于私人用途的工具上、或延续到工作时间之外时，使"同意"具有意义的那条边界，已不在量表所假定的位置。'),
      ],
      today=[
        P('Measure comprehensiveness, transparency, and consequence separately. A single monitoring intensity score cannot distinguish a system workers accept from one they resent.',
          '应分别测量全面性、透明度与后果。单一的监控强度分数无法区分员工接受的系统与他们反感的系统。'),
        P('Ask what workers believe is collected, not only what is collected. The perception is what the strain mechanism runs on.',
          '不仅要问"实际采集了什么"，还要问"员工认为采集了什么"。紧张机制正是建立在感知之上的。'),
      ]),

    # ------------------------------------------------ algorithmic transparency
    D('algorithmic-transparency',
      era='Emerged in the mid-2010s from fairness and accountability research; contested from the outset and increasingly regulated.',
      era_zh='2010 年代中期从公平与问责研究中出现，从一开始就存在争议，且日益受到监管。',
      situation=[
        P('As consequential decisions moved into systems, the affected party lost the ability to ask why. Existing procedural fairness research assumed a decision maker who could in principle explain, and that assumption no longer held.',
          '当重要决策转入系统之后，受影响者失去了追问"为什么"的能力。既有的程序公平研究假定存在原则上能够解释的决策者，而这一假定已不再成立。'),
        P('Transparency was proposed as the remedy, but it names an outcome rather than a mechanism: what has to be disclosed, to whom, and in what form were left open and are still being worked out.',
          '透明度被提出作为补救，但它命名的是结果而非机制：要披露什么、向谁披露、以何种形式披露，都被留待解决，至今仍在探索。'),
      ],
      argument=[
        P('The construct is the degree to which the logic, inputs, and consequences of a system are made intelligible to those subject to it. Intelligibility is the operative word: disclosure that cannot be understood does not produce transparency.',
          '该构念指系统的逻辑、输入与后果对受其影响者的可理解程度。关键词是"可理解"：无法被理解的披露并不产生透明度。'),
        P('It is audience relative. What makes a system transparent to an auditor, a regulator, an operator, and a subject are different disclosures, and a study that does not name the audience has not specified the construct.',
          '它是相对于受众而言的。使系统对审计者、监管者、操作者与受影响者透明的，是不同的披露内容；不指明受众的研究并未界定该构念。'),
        P('It is theorized to work through procedural fairness and trust: knowing how a decision was reached makes an unfavourable outcome more acceptable, which is why transparency effects appear even when the decision does not change.',
          '其作用机制被设定为经由程序公平与信任：知道决策如何作出，会使不利结果更可接受——这正是即便决策未变、透明度效应仍会出现的原因。'),
      ],
      development=[
        P('Research separated transparency about the system from explanation of a specific decision, since a person contesting an outcome needs the second and a regulator assessing a system needs the first.',
          '研究把"关于系统的透明"与"对具体决策的解释"分开：申诉某一结果的个人需要后者，评估系统的监管者需要前者。'),
      ],
      debates=[
        Debate('Does more transparency always help?', '透明度越高总是越好吗？',
               [Pos('Accountability position',
                    'Disclosure enables contestation and correction, and without it there is no route to accountability at all.',
                    '披露使申诉与纠正成为可能；没有它，问责根本无路可走。'),
                Pos('Countervailing position',
                    'Full disclosure enables gaming, can expose personal data, and detailed explanation of an unfavourable decision sometimes lowers acceptance rather than raising it.',
                    '完全披露会招致博弈、可能暴露个人数据；而对不利决策的详细解释，有时降低而非提高接受度。')],
               'Open. Evidence that explanation can reduce acceptance when it reveals the decision was mechanical is the most interesting recent finding.',
               '未决。"解释在揭示决策是机械作出时反而降低接受度"是近期最有意思的发现。'),
      ],
      theoretical=[
        P('Transparency, explainability, and interpretability are used interchangeably despite naming different things: what is disclosed, what account is given, and whether a human can follow the model.',
          '透明度、可解释性与可理解性被混用，尽管它们指称不同事物：披露了什么、给出了什么说法、以及人能否跟得上模型。'),
        P('The construct assumes an explanation faithful to the system. A post-hoc rationalization that is intelligible but not how the decision was made increases perceived transparency while reducing actual accountability.',
          '该构念假定解释忠实于系统。事后合理化若可理解却并非决策的真实过程，会提高感知透明度、却降低实际问责。'),
      ],
      empirical=[
        P('Most evidence comes from vignette experiments where participants read a description of a system rather than being subject to one, so stakes and recourse are absent.',
          '多数证据来自情境实验：被试阅读关于某系统的描述，而非真正受其决定，因此利害与救济途径都不存在。'),
        P('Manipulations vary explanation length or detail rather than faithfulness, so they may be measuring reaction to receiving an account rather than to understanding the system.',
          '实验操纵的是解释的长度或细节而非忠实度，因此可能测的是"收到一个说法"的反应，而非"理解了系统"的反应。'),
      ],
      temporal=[
        P('The construct was formed around models whose logic could in principle be stated — a scorecard, a rule set, a tree. Where the system is a large model whose behaviour cannot be summarized faithfully even by its developers, the construct as originally defined may not be satisfiable, and studies should say which kind of system they are about.',
          '该构念围绕"逻辑原则上可陈述"的模型形成——评分卡、规则集、决策树。当系统是连开发者也无法忠实概括其行为的大模型时，按原初定义的构念可能无法满足；研究应说明自己针对的是哪一类系统。'),
        P('It was theorized before disclosure became a legal requirement in some jurisdictions. Where explanation is mandated, transparency is partly a compliance artefact, and its effect on trust may differ from transparency offered voluntarily.',
          '它成形于某些法域将披露立为法定要求之前。当解释是强制的，透明度部分成为合规产物，其对信任的作用可能不同于自愿提供的透明度。'),
      ],
      today=[
        P('Name the audience and the object: transparency about the system or explanation of a decision. These are different constructs with different effects.',
          '应指明受众与对象：是关于系统的透明，还是对某项决策的解释。二者是不同构念，效应也不同。'),
        P('Manipulate faithfulness where possible, not just detail. Whether the explanation is true is the part that determines accountability.',
          '尽可能操纵忠实度而非仅仅细节。解释是否为真，才是决定问责的那一部分。'),
      ]),

    # -------------------------------------------------------- perceived usefulness
    D('perceived-usefulness',
      era='Operationalized in 1989 and carried essentially unchanged through three decades of adoption research.',
      era_zh='1989 年完成操作化，此后三十年的采纳研究中基本原样沿用。',
      situation=[
        P('Adoption research needed a belief that a designer could act on. Attitude was too diffuse and satisfaction came only after use, so what was wanted was a forward-looking judgement about benefit.',
          '采纳研究需要一个设计者可以着力的信念。态度过于弥散，满意度又只在使用之后才产生；因此需要的是一个关于收益的前瞻性判断。'),
        P('Perceived usefulness supplied it: the degree to which a person believes using a system would enhance their performance, which is specific enough to be designed for and general enough to apply across systems.',
          '感知有用性提供了这一点：个体相信使用某系统会提升其绩效的程度——它具体到可以据以设计，又通用到可跨系统适用。'),
      ],
      argument=[
        P('It is defined relative to job performance, not to enjoyment or ease. That distinction is what separates it from perceived ease of use and from hedonic constructs, and it is frequently blurred in application.',
          '它是相对于工作绩效定义的，而非相对于愉悦或轻松。这一区分使它有别于感知易用性与享乐类构念，而在应用中常被模糊。'),
        P('It consistently outperforms ease of use as a predictor of intention, which is the most replicated finding in this literature and the reason usefulness is treated as the primary lever.',
          '作为意向的预测变量，它一贯优于易用性——这是该文献中被复制最多的发现，也是有用性被视为主要杠杆的原因。'),
      ],
      development=[
        P('Later models decomposed it into job relevance, output quality, and result demonstrability, on the reasoning that a designer can act on those but not on usefulness directly.',
          '后续模型把它分解为工作相关性、产出质量与结果可展示性，理由是设计者能作用于这些，却无法直接作用于"有用性"。'),
      ],
      debates=[
        Debate('Does perceived usefulness predict use or rationalize it?', '感知有用性是预测使用，还是为使用作合理化？',
               [Pos('Predictive position',
                    'It is measured before adoption in longitudinal designs and predicts subsequent use, so the ordering is established.',
                    '在纵向设计中它于采纳前测得并预测后续使用，因此顺序已被确立。'),
                Pos('Rationalization critique',
                    'Most studies measure it concurrently with or after use, and people who already use a system report it as useful, which reverses the causal reading.',
                    '多数研究在使用的同时或之后测量它，而已在使用系统的人会报告它有用，这会使因果解读反转。')],
               'Longitudinal evidence supports prediction, but the majority of published tests cannot distinguish the two.',
               '纵向证据支持预测方向，但多数已发表检验无法区分二者。'),
      ],
      theoretical=[
        P('It presumes the user knows what the system does well enough to judge benefit. For systems whose output varies probabilistically, that judgement is unstable in a way the construct treats as fixed.',
          '它预设用户足够了解系统的功能以判断收益。对输出具有概率性的系统而言，这一判断并不稳定，而构念却把它当作固定的。'),
        P('It is individual and performance framed, so benefits that accrue to a team or that show up as reduced effort rather than better output are not captured.',
          '它以个体与绩效为框架，因此归于团队的收益、或表现为"省力"而非"更好产出"的收益，都不在捕捉范围内。'),
      ],
      empirical=[
        P('Items are close in wording to intention items, so the strong correlation between them is partly a measurement artefact.',
          '题项措辞与意向题项接近，二者之间的强相关部分是测量假象。'),
        P('It is almost always measured by self-report in the same instrument as intention and self-reported use, which is the weakest design for the causal claim being made.',
          '它几乎总是与意向及自评使用在同一工具中自评测量，而这对所提出的因果主张是最弱的设计。'),
      ],
      temporal=[
        P('The construct assumes a stable system with a knowable benefit. Where capability changes between versions and output quality varies by prompt or context, a single usefulness judgement summarizes an experience that was not uniform, and repeated measurement may be required for it to mean anything.',
          '该构念假定系统稳定、收益可知。当能力随版本变化、输出质量随提示或情境波动时，单次有用性判断概括的是一段并不均质的体验；要使它有意义，可能需要重复测量。'),
        P('It was written for tools that supplement the user. Where a system performs the task and the user supervises it, performance enhancement is an ambiguous referent, and workers may rate a system useful while it displaces the part of the job they valued.',
          '它写给的是"辅助用户"的工具。当系统执行任务而用户监督它时，"提升绩效"的指称变得含混：员工可能给系统很高的有用性评分，而它正在取代他们所看重的那部分工作。'),
      ],
      today=[
        P('Measure it before use and use again after, or state plainly that the design cannot separate prediction from rationalization.',
          '应在使用前测量、使用后再测一次；否则应明确说明该设计无法区分预测与合理化。'),
        P('For AI tools, decompose the judgement rather than asking about usefulness in general. Which task, at what quality, with how much checking, is the informative question.',
          '对 AI 工具，应分解该判断而非笼统询问有用性。哪项任务、达到什么质量、需要多少复核，才是有信息量的问题。'),
      ]),

    # ---------------------------------------------------------- privacy concern
    D('privacy-concern',
      era='Instrumented for information systems research from the mid-1990s; the privacy paradox documented consistently since the 2000s.',
      era_zh='1990 年代中期为信息系统研究形成量表，隐私悖论自 2000 年代起被持续记录。',
      situation=[
        P('As organizations began collecting personal data at scale, research needed to know whether people minded and what they would do about it. Concern was the natural construct and was assumed to predict behaviour.',
          '当组织开始大规模采集个人数据，研究需要知道人们是否介意、以及会采取什么行动。关注度是自然的构念，并被假定能预测行为。'),
        P('It did not. The persistent finding is that stated concern is high and disclosure behaviour is nonetheless extensive, which is the privacy paradox and the organizing problem of this literature.',
          '事实并非如此。持续出现的发现是：陈述的关注度很高，披露行为却依然广泛——这就是隐私悖论，也是该文献的组织性问题。'),
      ],
      argument=[
        P('The construct is concern about the collection, control, and use of personal information, usually decomposed into collection, unauthorized secondary use, improper access, and errors.',
          '该构念指对个人信息的采集、控制与使用的关注，通常分解为采集、未经授权的二次使用、不当访问与错误四个维度。'),
        P('It is theorized as the cost side of the privacy calculus: concern is weighed against expected benefit, and disclosure follows when benefit dominates. The paradox is then not a paradox but a trade-off resolved in favour of benefit.',
          '它被设定为隐私计算中的成本一侧：关注度与预期收益相权衡，收益占优时发生披露。如此，悖论便不是悖论，而是权衡后倒向收益的结果。'),
      ],
      development=[
        P('Explanations for the gap multiplied: immediate benefit against distant risk, absence of a real alternative, resignation, and the cognitive cost of evaluating a policy nobody reads.',
          '对这一落差的解释不断增加：即时收益对远期风险、缺乏真实替代选项、无奈接受，以及评估无人阅读的隐私政策所需的认知成本。'),
      ],
      debates=[
        Debate('Is the privacy paradox a paradox?', '隐私悖论是悖论吗？',
               [Pos('Measurement position',
                    'General concern and specific disclosure are different constructs at different levels of abstraction; measured at the same specificity they align, so there is no paradox to explain.',
                    '一般性关注与具体披露是抽象层次不同的两个构念；在同等具体程度上测量时二者是一致的，因此没有悖论需要解释。'),
                Pos('Structural position',
                    'The gap is real but reflects absence of choice and resignation rather than an inconsistency in the person, so attributing it to attitude-behaviour inconsistency misplaces the explanation.',
                    '落差真实存在，但反映的是缺乏选择与无奈接受，而非个体自身的不一致；把它归因于态度—行为不一致是把解释放错了地方。')],
               'Both have support, and they imply different remedies: better measurement versus changed conditions.',
               '两者都有支持，且意味着不同的补救方向：改进测量，还是改变条件。'),
      ],
      theoretical=[
        P('Concern is treated as an individual attitude, but whether disclosure is voluntary depends on market structure. A construct measuring how a person feels cannot represent the absence of an alternative.',
          '关注度被当作个体态度，而披露是否自愿取决于市场结构。一个测量"个体感受"的构念无法表达"没有替代选项"。'),
        P('The calculus framing assumes deliberation, which fits a consequential one-off disclosure much better than the routine, repeated, low-salience disclosures that make up most data collection.',
          '计算式框架假定深思熟虑，这更适合重大的一次性披露，而非构成大部分数据采集的那种日常、重复、低显著度的披露。'),
      ],
      empirical=[
        P('Stated concern is measured in a survey where privacy is made salient by the questions themselves, which is exactly the condition under which behaviour is not observed.',
          '陈述的关注度是在问卷中测量的，而问题本身使隐私变得显著——这恰恰是行为不被观察的情境。'),
        P('Disclosure is usually hypothetical or scenario based; studies observing actual disclosure with real consequences are rare and find smaller effects.',
          '披露通常是假想或情境式的；观察带真实后果的实际披露的研究很少，且所得效应更小。'),
      ],
      temporal=[
        P('The instruments were written when data collection was an identifiable event a person could notice and consent to. Where collection is ambient, inferred, and continuous, there is no moment of disclosure to be concerned about, and a scale asking about providing information does not describe what is happening.',
          '量表写于"数据采集是个体能察觉并同意的可辨识事件"的时期。当采集是环境式的、推断式的、持续的，就不存在可供担忧的披露时刻；询问"是否提供信息"的量表并未描述实际发生的事。'),
        P('It was developed before inference from non-sensitive data became routine. A person can be concerned about sharing sensitive information while freely providing the behavioural traces from which it is derived, and the construct does not distinguish the two.',
          '它发展于"从非敏感数据推断敏感信息"成为常规之前。个体可以对分享敏感信息表示担忧，同时自由提供可据以推导出该信息的行为痕迹，而构念并不区分二者。'),
      ],
      today=[
        P('Match the specificity of the concern measure to the behaviour being predicted. Much of the paradox disappears when the two are at the same level.',
          '应使关注度测量的具体程度与所预测的行为相匹配。当二者处于同一层次时，悖论的大部分即告消失。'),
        P('Ask whether an alternative existed. Disclosure without a choice is not evidence about preference, and treating it as such is the main way this literature overreaches.',
          '应追问是否存在替代选项。没有选择余地的披露不构成关于偏好的证据；把它当作证据，正是这一文献主要的过度推论。'),
      ]),
])
