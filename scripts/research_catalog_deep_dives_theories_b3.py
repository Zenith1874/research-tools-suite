# -*- coding: utf-8 -*-
"""Deep dives for catalog theories, batch 3.

Network and capability theories: social capital, structural holes, absorptive
capacity, ambidexterity, real options, and contingency theory. The first two
share a mechanism and are cross-referenced rather than repeated.

Schema helpers live in ``research_catalog_deep_dives``.
"""

from research_catalog_deep_dives import D, Debate, P, Pos

THEORY_DIVES_B3 = dict([

    # ------------------------------------------------------- social capital
    D('social-capital-theory',
      era='Formulated in sociology through the 1980s; brought into organizational research in 1998 with a three-dimensional structure.',
      era_zh='1980 年代在社会学中成形，1998 年以三维结构进入组织研究。',
      situation=[
        P('Human capital explained why an individual with more skill earns more, but not why two equally skilled people receive very different opportunities. Something about position in a structure of relationships was doing work that individual attributes could not.',
          '人力资本解释了技能更高者为何收入更高，却解释不了两个技能相当的人为何获得截然不同的机会。关系结构中的位置在起作用，而这是个体属性无法解释的。'),
        P('The proposal was that relationships are themselves a form of capital: resources are embedded in a network and become available through it, so the network is an asset rather than merely a channel.',
          '该理论主张关系本身即是一种资本：资源嵌入于网络之中并经由网络变得可动员，因此网络是一项资产，而不只是一条通道。'),
      ],
      argument=[
        P('The organizational formulation separates three dimensions. The structural dimension is the pattern of ties — who is connected to whom. The relational dimension is the quality of those ties, principally trust and obligation. The cognitive dimension is shared language and understanding that makes exchange possible at all.',
          '组织层面的表述区分三个维度：结构维度是联结的格局——谁与谁相连；关系维度是这些联结的质量，主要是信任与义务；认知维度是使交换得以发生的共享语言与理解。'),
        P('The three are not substitutes. A dense network without shared understanding cannot transfer complex knowledge, and shared understanding without ties has no route to travel.',
          '三者并非彼此替代。缺乏共享理解的密集网络无法传递复杂知识；缺乏联结的共享理解则没有传递路径。'),
        P('The mechanism is access and mobilization: social capital predicts outcomes when a resource is both reachable through the network and actually activated, which is why possession of ties alone is a weak predictor.',
          '机制在于可及与动员：只有当资源既可经由网络触及、又确实被激活时，社会资本才预测结果——这正是"仅拥有联结"预测力很弱的原因。'),
      ],
      development=[
        P('The bonding and bridging distinction separated capital that comes from closure within a group from capital that comes from spanning between groups, and the two predict different outcomes.',
          '黏合型与桥接型的区分，把"来自群体内部闭合"的资本与"来自跨越群体"的资本分开，二者预测不同的结果。'),
      ],
      debates=[
        Debate('Does closure or brokerage produce more advantage?', '闭合与中介，哪种带来更多优势？',
               [Pos('Closure position',
                    'Dense networks enforce norms and build the trust that makes complex cooperation possible, which brokerage cannot supply.',
                    '密集网络能执行规范、建立使复杂合作成为可能的信任，而中介位置无法提供这些。'),
                Pos('Brokerage position',
                    'Redundant ties carry redundant information; advantage comes from spanning gaps, as the structural holes account argues.',
                    '冗余联结传递冗余信息；优势来自跨越结构空洞，这正是结构洞理论的主张。')],
               'Long-running and context dependent. The productive reading is that they solve different problems: closure for trust and enforcement, brokerage for novelty.',
               '长期争论且依情境而定。有建设性的读法是二者解决不同问题：闭合用于信任与执行，中介用于新颖性。'),
      ],
      theoretical=[
        P('The term is applied to network structure, to trust, and to norms interchangeably, so two studies claiming to measure social capital may share nothing but the label.',
          '该术语被交替用于网络结构、信任与规范，因此两项都自称测量社会资本的研究，可能除了标签之外毫无共同之处。'),
        P('It is treated as an unqualified good, though closure also enforces obsolete norms and excludes outsiders, and those are consequences of the same mechanism.',
          '它被当作无条件的好事，然而闭合同样会强化过时规范并排斥外部人——这些是同一机制的后果。'),
      ],
      empirical=[
        P('Social capital and its outcomes reinforce each other over time, so cross-sectional estimates cannot separate the return on a network from the network that success builds.',
          '社会资本与其结果随时间相互强化，因此横截面估计无法把"网络的回报"与"成功所建立的网络"分开。'),
        P('Network boundaries are set by the researcher, and measures of structure are sensitive to that choice in ways rarely reported.',
          '网络边界由研究者划定，结构性指标对这一选择相当敏感，而这一点很少被报告。'),
      ],
      temporal=[
        P('The construct assumes ties are costly to form and maintain, which is what makes a network an asset. Where connections can be made at negligible cost and are visible to everyone, the scarcity that gave structural position its value is weaker, and tie counts measure something closer to visibility than to mobilizable resource.',
          '该构念假定联结的建立与维持代价高昂，这正是网络成为资产的原因。当连接可以近乎零成本建立且对所有人可见时，赋予结构位置以价值的稀缺性被削弱，联结数量所测的更接近"可见度"而非"可动员资源"。'),
        P('It was theorized for networks people could enumerate and describe. Where ties are inferred from platform interaction logs, the observed network is the one the platform records, which may differ substantially from the one that carries obligation.',
          '它针对的是人们能够枚举与描述的网络。当联结从平台互动日志中推断时，被观察到的网络是平台所记录的那个，可能与真正承载义务的网络相去甚远。'),
      ],
      today=[
        P('Specify which dimension the argument uses and measure that one. A study about knowledge transfer needs the cognitive dimension; a tie count will not stand in for it.',
          '应指明论证使用哪一个维度并测量该维度。研究知识转移需要认知维度，联结计数无法代替它。'),
        P('Design for activation rather than possession. Whether the resource was actually mobilized is the part of the mechanism most studies leave unobserved.',
          '设计上应关注"动员"而非"拥有"。资源是否真被动员，是多数研究未加观察的那部分机制。'),
      ]),

    # ---------------------------------------------------- structural holes
    D('structural-holes-theory',
      era='Published in 1992; the brokerage-versus-closure debate ran through the 2000s and remains open.',
      era_zh='1992 年提出，"中介 vs 闭合"之争贯穿 2000 年代，至今未决。',
      situation=[
        P('Network research had established that ties matter, and the intuitive reading was that more ties are better. That could not explain why some well-connected actors gained little while others with fewer ties gained a great deal.',
          '网络研究已确立联结重要，直觉读法是联结越多越好。但这解释不了：为何有些人脉广博者获益甚少，而另一些联结更少的人获益很多。'),
        P('The insight was that what matters is not the number of ties but their non-redundancy. Ties to people who already know each other carry the same information twice.',
          '洞见在于：重要的不是联结数量，而是其非冗余性。通往彼此已相识者的联结，把同样的信息传递了两遍。'),
      ],
      argument=[
        P('A structural hole is the gap between two contacts who are not connected to each other. An actor spanning that gap receives non-redundant information from both sides and can control what passes between them.',
          '结构洞是两个彼此不相连的联系人之间的空隙。跨越该空隙的行动者从两侧获得非冗余信息，并能控制两者之间传递什么。'),
        P('Two benefits follow: information advantage, from access to different worlds earlier than others, and control advantage, from being the party through whom coordination must pass.',
          '由此产生两种收益：信息优势，比他人更早接触不同世界；控制优势，成为协调必须经过的那一方。'),
        P('Constraint is the operational measure — how far an actor contacts are concentrated among people who are also connected to each other. Low constraint means many holes spanned.',
          '约束度是操作化指标——行动者的联系人在多大程度上集中于彼此也相互连接的人群中。低约束意味着跨越了较多空洞。'),
      ],
      development=[
        P('Later work qualified the benefit by whether the actor can act on the position: brokerage requires the skill and standing to combine what the two sides know, not merely to sit between them.',
          '后续研究以"行动者能否利用该位置"限定其收益：中介需要把两侧所知加以组合的能力与地位，而不只是坐在中间。'),
      ],
      debates=[
        Debate('Is brokerage always beneficial?', '中介总是有益的吗？',
               [Pos('Brokerage position',
                    'Non-redundant access to distant information is the source of novel combinations, and constraint predicts outcomes across many settings.',
                    '对远端信息的非冗余获取是新颖组合的来源，而约束度在多种情境中都能预测结果。'),
                Pos('Cost position',
                    'Brokerage carries social costs — distrust from both sides, the effort of maintaining disconnected relations — and in cohesive settings it can damage standing.',
                    '中介带有社会成本——两侧的不信任、维护互不相连关系的精力——在高凝聚情境中甚至可能损害地位。')],
               'Open. The evidence supports brokerage for information benefits and closure for trust and enforcement, which are different outcomes rather than a contradiction.',
               '未决。证据支持中介带来信息收益、闭合带来信任与执行力——这是不同结果，而非彼此矛盾。'),
      ],
      theoretical=[
        P('The theory explains the value of a position but not how an actor comes to occupy it, and selection into broker positions is likely non-random.',
          '理论解释了位置的价值，却不解释行动者如何取得该位置，而进入中介位置很可能是非随机的。'),
        P('It assumes information passing through the broker is not otherwise available. Where both sides can search independently, the information advantage attenuates.',
          '它假定经由中介传递的信息在其他途径下不可得。当两侧都能独立检索时，信息优势随之减弱。'),
      ],
      empirical=[
        P('Constraint is computed from an observed network whose boundary the researcher chose, and missing ties mechanically inflate apparent brokerage.',
          '约束度由研究者划定边界的观察网络计算而来，遗漏的联结会机械性地夸大表面上的中介程度。'),
        P('Most evidence is cross-sectional, so the possibility that successful actors acquire broker positions rather than benefit from them is rarely excluded.',
          '多数证据是横截面的，因此"成功者获得中介位置"而非"中介位置带来成功"这一可能性很少被排除。'),
      ],
      temporal=[
        P('The mechanism depends on information not flowing between the two sides by other routes. Where both contacts read the same feeds, use the same search, and belong to the same public platforms, the hole may exist in the tie network while the information gap it was supposed to create does not.',
          '该机制依赖"信息不会经其他路径在两侧之间流动"。当两个联系人阅读同样的信息流、使用同样的检索、属于同样的公共平台时，空洞可能在联结网络中存在，而它本应造成的信息落差并不存在。'),
        P('Control advantage assumed the broker could manage what each side knew about the other. Where interactions are logged and visible, that control is substantially reduced.',
          '控制优势假定中介者能掌控两侧对彼此的了解。当互动被记录且可见时，这种控制大幅削弱。'),
      ],
      today=[
        P('Report the network boundary and missing-tie coverage before interpreting constraint. Apparent brokerage is the measure most sensitive to unobserved ties.',
          '在解读约束度之前应报告网络边界与遗漏联结的覆盖情况。表面上的中介是对未观察联结最敏感的指标。'),
        P('Where information is publicly searchable, argue why the hole still carries an information advantage rather than assuming it does.',
          '当信息可公开检索时，应论证该空洞为何仍带来信息优势，而不是直接假定如此。'),
      ]),

    # ------------------------------------------------------ absorptive capacity
    D('absorptive-capacity',
      era='Introduced in 1990; reconceptualized into potential and realized components in 2002.',
      era_zh='1990 年提出，2002 年被重构为潜在能力与已实现能力两部分。',
      situation=[
        P('Firms were investing in R&D and receiving very different returns, and access to external knowledge — publications, suppliers, universities — did not translate into use in any consistent way.',
          '企业投入研发却获得差异极大的回报，而对外部知识——文献、供应商、大学——的获取，并未以任何一致的方式转化为实际使用。'),
        P('The explanation offered was that receiving knowledge is not passive. A firm can only recognize the value of something it is already close to understanding, so prior knowledge determines what can be absorbed.',
          '给出的解释是：接收知识并非被动过程。企业只能识别自己已接近理解之物的价值，因此既有知识决定了能吸收什么。'),
      ],
      argument=[
        P('Absorptive capacity is the ability to recognize the value of new external information, assimilate it, and apply it commercially. It is a function of related prior knowledge, which makes it path dependent.',
          '吸收能力是识别外部新信息的价值、消化它并将其商业化应用的能力。它是既有相关知识的函数，因而具有路径依赖性。'),
        P('The reconceptualization split it in two. Potential capacity is acquisition and assimilation — getting knowledge in. Realized capacity is transformation and exploitation — turning it into something the firm does. A firm can be strong on one and weak on the other, and the gap explains why some firms scan widely and change nothing.',
          '重构把它一分为二：潜在能力是获取与消化——把知识引进来；已实现能力是转化与利用——把它变成企业实际所做之事。企业可能一强一弱，而这一落差解释了为何有些企业广泛扫描却毫无改变。'),
        P('R&D therefore has a dual role: it produces innovation and it simultaneously builds the capacity to absorb what others produce.',
          '因此研发具有双重作用：既产生创新，又同时构建吸收他人成果的能力。'),
      ],
      development=[
        P('The construct was extended downward to individuals and teams and upward to alliances and regions, which broadened its use while making cross-level comparison harder.',
          '该构念向下扩展到个体与团队、向上扩展到联盟与区域，这拓宽了应用范围，也使跨层次比较更加困难。'),
      ],
      debates=[
        Debate('Is R&D intensity an acceptable proxy?', '研发强度是可接受的代理吗？',
               [Pos('Practical position',
                    'R&D spend is available, comparable, and theoretically linked to the capacity through the dual-role argument.',
                    '研发支出可得、可比，且经由双重作用论证与该能力在理论上相连。'),
                Pos('Validity critique',
                    'Spending is an input and capacity is an ability; a firm can spend heavily and absorb nothing, which is precisely the variance the construct was invented to explain.',
                    '支出是投入，能力是本领；企业可以重金投入却毫无吸收——而这恰恰是该构念被发明来解释的那部分差异。')],
               'The critique is accepted in principle; R&D intensity remains the dominant measure in practice.',
               '该批评在原则上被接受，研发强度在实践中仍是主导指标。'),
      ],
      theoretical=[
        P('Path dependence means the construct explains why firms cannot absorb distant knowledge, which is also the case where absorption would matter most.',
          '路径依赖意味着该构念解释了企业为何无法吸收远端知识——而那恰恰是吸收最重要的情形。'),
        P('Potential and realized capacity have different antecedents but are frequently collapsed into one score, which discards the distinction the 2002 restatement introduced.',
          '潜在能力与已实现能力前因不同，却常被压成一个分数，从而丢弃了 2002 年重述所引入的区分。'),
      ],
      empirical=[
        P('The construct is regularly inferred from the outcome it should predict: a firm that used external knowledge is said to have had absorptive capacity, which cannot support the causal claim.',
          '该构念常从它本应预测的结果反推：使用了外部知识的企业被说成具有吸收能力，而这无法支撑因果主张。'),
        P('Patent-citation measures capture codified knowledge flows only and miss absorption through hiring, informal contact, and reverse engineering.',
          '专利引用指标只捕捉编码化的知识流动，遗漏了经由招聘、非正式接触与逆向工程发生的吸收。'),
      ],
      temporal=[
        P('The construct was built for knowledge that had to be acquired and internalized before it could be used. Where capability can be accessed as a service without being understood — a model called through an interface, an analytic pipeline bought whole — a firm can exploit external knowledge with little assimilation, which the framework treats as impossible.',
          '该构念针对的是"必须先获取并内化才能使用"的知识。当能力可以作为服务被调用而无需被理解时——通过接口调用的模型、整体购入的分析流水线——企业可以在几乎不消化的情况下利用外部知识，而框架把这视为不可能。'),
        P('It assumes prior knowledge is the binding constraint on recognition. Where recommendation and search systems surface relevant external knowledge, part of the recognition function is performed outside the firm, and a firm with little prior knowledge may still be pointed at what matters.',
          '它假定既有知识是"识别"的约束条件。当推荐与检索系统主动呈现相关外部知识时，部分识别功能是在企业之外完成的，既有知识很少的企业仍可能被指向真正重要的东西。'),
      ],
      today=[
        P('Measure the capacity separately from the outcome, and separate potential from realized. A single composite predicted by R&D spend tests almost nothing.',
          '应把能力与结果分开测量，并区分潜在与已实现。由研发支出预测的单一合成分数几乎什么都没检验。'),
        P('For AI and platform capability, state whether absorption is actually required. Where a capability is consumed as a service, the theory mechanism may not be operating at all.',
          '研究 AI 与平台能力时，应说明是否真的需要"吸收"。当能力是作为服务被消费时，该理论的机制可能根本没有运作。'),
      ]),

    # ------------------------------------------------- organizational ambidexterity
    D('organizational-ambidexterity',
      era='Framed as an exploration-exploitation tension in 1991; developed into structural, contextual, and sequential solutions from 1996.',
      era_zh='1991 年被表述为探索—利用张力，1996 年起发展出结构型、情境型与时序型三种解法。',
      situation=[
        P('Organizational learning research had a problem it could state precisely: refining what you already do produces reliable near-term returns, while searching for new possibilities produces uncertain and distant ones.',
          '组织学习研究提出了一个可以被精确陈述的问题：精进已有之事带来可靠的近期回报，而探索新可能带来不确定且遥远的回报。'),
        P('Because both draw on the same scarce resources and attention, and because exploitation pays off sooner and more visibly, organizations drift toward it and become good at something the environment no longer rewards.',
          '由于二者争夺同样稀缺的资源与注意力，且利用的回报更早、更可见，组织会向利用漂移，最终精通于环境不再奖赏之事。'),
      ],
      argument=[
        P('The tension is structural, not a failure of will. An organization optimized for efficiency develops routines, metrics, and selection processes that systematically disadvantage exploration.',
          '这一张力是结构性的，而非意志薄弱。为效率优化的组织会发展出惯例、指标与选拔机制，系统性地不利于探索。'),
        P('Three solutions are proposed. Structural ambidexterity separates the two into different units with different cultures, joined at the top. Contextual ambidexterity builds a setting where individuals divide their own attention. Sequential ambidexterity cycles between them over time.',
          '提出了三种解法：结构型把二者分置于文化不同的单元、在高层衔接；情境型营造让个体自行分配注意力的环境；时序型则随时间在二者之间轮替。'),
        P('These are not interchangeable. Structural separation suits radically different activities; contextual suits work where the same people must do both; sequential suits environments that change in discrete waves.',
          '三者不可互替。结构分离适用于性质迥异的活动；情境型适用于同一批人必须两者兼顾的工作；时序型适用于以离散波次变化的环境。'),
      ],
      development=[
        P('Attention shifted to the integration problem: separated units produce exploration that the mainstream organization then refuses to absorb, so the top-team mechanism became the object of study.',
          '关注点转向整合问题：分离的单元产生了探索成果，主体组织却拒绝吸收，因此高层团队机制成为研究对象。'),
      ],
      debates=[
        Debate('Are exploration and exploitation a continuum or orthogonal?', '探索与利用是连续体还是正交的？',
               [Pos('Continuum position',
                    'They compete for the same resources, so more of one necessarily means less of the other and they should be modelled as a trade-off.',
                    '二者争夺同样的资源，因此其中一方增加必然意味着另一方减少，应作为取舍来建模。'),
                Pos('Orthogonal position',
                    'With sufficient slack an organization can raise both, so they should be modelled as separate dimensions and their combination measured.',
                    '在冗余充足时组织可以同时提高两者，因此应作为独立维度建模并测量其组合。')],
               'Unresolved, and it determines the measure: a difference score versus a product, which produce different results on the same data.',
               '未决，且它决定了测量方式：差值还是乘积——二者在同一数据上给出不同结果。'),
      ],
      theoretical=[
        P('The benefit is contingent on environmental dynamism and slack, so a general claim that ambidexterity improves performance is not what the theory predicts.',
          '其收益取决于环境动态性与冗余，因此"双元提升绩效"这一一般性主张并非理论的预测。'),
        P('Ambidexterity is defined at the organizational level but is often measured by asking individuals about their own behaviour, which is a different construct.',
          '双元定义在组织层面，却常通过询问个体自身行为来测量，而那是另一个构念。'),
      ],
      empirical=[
        P('The two activities are typically measured with self-report scales in the same survey as performance, so the relationship is established by common-source association.',
          '两类活动通常以自评量表与绩效在同一份问卷中测量，其关系由同源关联确立。'),
        P('Because measures differ — difference scores, products, separate dimensions — pooled evidence across studies is difficult to interpret.',
          '由于测量方式不同——差值、乘积、独立维度——跨研究的合并证据难以解读。'),
      ],
      temporal=[
        P('The structural solution assumes exploration requires a separate unit with different routines, which was expensive and therefore a real commitment. Where experimentation can be run continuously at low cost inside the main organization, the case for structural separation weakens and the theory prescription may be more expensive than the problem.',
          '结构型解法假定探索需要拥有不同惯例的独立单元，这在当时成本高昂、因而是一项真实承诺。当实验可以在主体组织内部低成本持续进行时，结构分离的理由被削弱，理论开出的处方可能比问题本身更昂贵。'),
        P('The framework assumes exploration is slow and lumpy. Where a new capability can be trialled in days, the sequential solution timing logic — long cycles between modes — no longer matches the pace at which the environment can be tested.',
          '框架假定探索缓慢且成块发生。当一项新能力可在数日内试验时，时序型解法的节奏逻辑——在两种模式之间长周期切换——已不匹配环境可被检验的速度。'),
      ],
      today=[
        P('State which form of ambidexterity the study is about and measure at the level where it is theorized. Individual-level scales do not test the structural argument.',
          '应说明研究关注哪种形式的双元，并在其理论所在的层面测量。个体层面量表无法检验结构型论证。'),
        P('Include dynamism and slack as conditions rather than controls. The theory predicts contingent benefit, and a pooled main effect is not what it claims.',
          '应把动态性与冗余作为条件而非控制变量。理论预测的是条件性收益，合并主效应并非其主张。'),
      ]),

    # ------------------------------------------------------- real options theory
    D('real-options-theory',
      era='Financial option logic extended to physical investment through the 1980s; consolidated in 1994 and applied to strategy from 1997.',
      era_zh='1980 年代把金融期权逻辑扩展到实物投资，1994 年集成，1997 年起应用于战略研究。',
      situation=[
        P('Discounted cash flow evaluated an investment as a now-or-never commitment, which systematically undervalued projects whose main benefit was the right to decide later.',
          '折现现金流把投资评估为"现在或永不"的承诺，因而系统性低估了那些主要收益在于"保留日后决定权"的项目。'),
        P('Option pricing had already solved the analogous problem for financial claims. Extending it to physical and strategic investment gave a way to value flexibility rather than treating it as unquantifiable.',
          '期权定价已为金融求偿权解决了类似问题。把它扩展到实物与战略投资，提供了给"灵活性"定价的方法，而不再把它当作无法量化之物。'),
      ],
      argument=[
        P('An investment under uncertainty carries option value when three conditions hold together: the commitment is at least partly irreversible, the outcome is uncertain, and the decision can be deferred or staged.',
          '不确定条件下的投资在三个条件同时成立时具有期权价值：承诺至少部分不可逆；结果不确定；决策可以推迟或分阶段进行。'),
        P('Remove any one and the option disappears. If the investment is reversible there is nothing to protect; if there is no uncertainty there is nothing to learn by waiting; if the decision cannot be deferred there is no choice to preserve.',
          '去掉任何一条，期权即告消失：投资可逆则无可保护；没有不确定性则等待无从学习；决策无法推迟则没有可保留的选择。'),
        P('The strategic implication is to stage commitment: invest enough to keep the option alive and to learn, and defer the irreversible part until uncertainty resolves.',
          '其战略含义是分阶段承诺：投入到足以保留期权并获得学习，把不可逆的部分推迟到不确定性消解之后。'),
      ],
      development=[
        P('Strategy research applied it to market entry, R&D staging, joint ventures, and platform investment, treating small early commitments as growth options on larger later ones.',
          '战略研究把它应用于市场进入、研发分阶段、合资与平台投资，把早期小额承诺视为对后续更大投入的增长期权。'),
      ],
      debates=[
        Debate('Do organizations actually exercise abandonment options?', '组织真的会行使放弃期权吗？',
               [Pos('Normative position',
                    'The framework prescribes abandoning when uncertainty resolves unfavourably, and the value of staging depends on doing so.',
                    '框架规定：当不确定性向不利方向消解时应当放弃，分阶段的价值正取决于此。'),
                Pos('Behavioural critique',
                    'Escalation of commitment, sunk-cost reasoning, and reputational stakes mean firms routinely fail to abandon, so the ex ante option value is not realized.',
                    '承诺升级、沉没成本推理与声誉压力使企业经常无法放弃，因而事前的期权价值并未实现。')],
               'Open. The behavioural evidence is strong enough that option value should be treated as an upper bound rather than an expectation.',
               '未决。行为证据足够有力，因而期权价值应被视为上界而非期望值。'),
      ],
      theoretical=[
        P('The financial analogy assumes the underlying asset is traded and its volatility observable. For strategic investments neither holds, so the valuation machinery transfers less cleanly than the logic does.',
          '金融类比假定标的资产可交易、其波动率可观察。对战略投资而言两者都不成立，因此定价机制的迁移不如其逻辑迁移得干净。'),
        P('Competitive interaction is largely absent: waiting has a cost when a rival can pre-empt, and the basic model treats the option as exclusive.',
          '竞争互动基本缺席：当对手可能抢先时，等待是有代价的，而基础模型把期权视为独占的。'),
      ],
      empirical=[
        P('Option value is not directly observable, so tests rely on proxies for uncertainty and irreversibility that also predict investment through other channels.',
          '期权价值不可直接观察，因此检验依赖不确定性与不可逆性的代理指标，而它们同样会经由其他渠道预测投资。'),
        P('Studies frequently infer that firms reasoned in option terms from investment patterns that a simple risk-aversion account would also produce.',
          '研究常从投资模式推断企业按期权逻辑思考，而简单的风险规避解释同样能产生这些模式。'),
      ],
      temporal=[
        P('The framework assumes irreversibility is the normal condition of investment — a plant, a market entry, a long-lived asset. Where capacity is rented, capability is consumed as a service, and commitments can be unwound in weeks, the irreversibility that creates option value is much reduced and standard valuation may be adequate.',
          '框架假定不可逆是投资的常态——一座工厂、一次市场进入、一项长寿命资产。当产能是租用的、能力作为服务消费、承诺可以在数周内解除时，创造期权价值的不可逆性大幅降低，标准估值可能已经够用。'),
        P('It also assumes uncertainty resolves through the passage of time. Where the relevant uncertainty is resolved by running an experiment rather than by waiting, the deferral option is worth less than an option to test, which the classical framing does not represent.',
          '它还假定不确定性随时间流逝而消解。当相关不确定性是通过做实验而非等待来消解时，推迟期权的价值低于"检验期权"，而经典表述并未表达后者。'),
      ],
      today=[
        P('Check the three conditions before invoking the framework. Without genuine irreversibility it is an elaborate way of saying the project is risky.',
          '在援引该框架前应核对三个条件。缺少真正的不可逆性，它只是"这个项目有风险"的一种复杂说法。'),
        P('Model the behavioural failure to abandon rather than assuming rational exercise. That gap is where most of the interesting variance in real investment sits.',
          '应对"未能放弃"这一行为失败加以建模，而非假定理性行权。真实投资中最有意思的差异，大多正落在这一落差里。'),
      ]),

    # -------------------------------------------------------- contingency theory
    D('contingency-theory',
      era='Established in the 1960s; the dominant organizational design framework into the 1980s and still the implicit default.',
      era_zh='1960 年代确立，直至 1980 年代都是组织设计的主导框架，至今仍是隐含的默认视角。',
      situation=[
        P('Classical management theory sought universal principles: the right span of control, the right degree of formalization. Empirical work kept finding that arrangements which worked in one setting failed in another.',
          '古典管理理论追求普遍原则：恰当的管理幅度、恰当的正式化程度。经验研究却不断发现：在一种情境中有效的安排，在另一种情境中失效。'),
        P('Rather than treat that as measurement error, contingency theory made it the finding: effectiveness depends on the match between structure and circumstance, so there is no single best way to organize.',
          '权变理论没有把这当作测量误差，而是把它当作发现本身：有效性取决于结构与情境的匹配，因此不存在唯一最优的组织方式。'),
      ],
      argument=[
        P('Structure should fit the contingencies the organization faces — principally environmental uncertainty, technology, size, and strategy. Fit produces performance; misfit produces underperformance.',
          '结构应与组织面对的权变因素相匹配——主要是环境不确定性、技术、规模与战略。匹配带来绩效，失配导致绩效不佳。'),
        P('Stable environments favour mechanistic structures with formal rules and clear hierarchy; uncertain environments favour organic structures with lateral communication and decentralized decisions.',
          '稳定环境有利于规则正式、层级清晰的机械式结构；不确定环境有利于横向沟通、决策分散的有机式结构。'),
        P('Differentiation and integration are the paired requirement: units facing different environments must be allowed to differ, and the more they differ the more integration mechanism is needed to hold them together.',
          '分化与整合是一对要求：面对不同环境的单元必须被允许有所不同，而它们差异越大，就越需要整合机制把它们维系在一起。'),
      ],
      development=[
        P('Fit was formalized in several incompatible ways — matching, moderation, mediation, and gestalt profiles — each implying a different statistical test on the same theoretical claim.',
          '"匹配"被以若干互不相容的方式形式化——匹配、调节、中介、格式塔剖面——每一种都意味着对同一理论主张采用不同的统计检验。'),
      ],
      debates=[
        Debate('What does fit mean operationally?', '"匹配"在操作层面意味着什么？',
               [Pos('Interaction position',
                    'Fit is a moderation effect: the benefit of a structural feature depends on the level of the contingency, testable with a product term.',
                    '匹配是调节效应：某结构特征的收益取决于权变因素的水平，可用乘积项检验。'),
                Pos('Profile position',
                    'Fit is multidimensional coherence: an organization matches an ideal configuration, and deviation on any dimension costs performance.',
                    '匹配是多维一致性：组织与某个理想配置相符，任一维度的偏离都会损害绩效。')],
               'Unresolved, and results differ by operationalization on the same data, which is a large part of why the literature did not converge.',
               '未决，且在同一数据上不同操作化会给出不同结果——这在很大程度上解释了该文献为何未能收敛。'),
      ],
      theoretical=[
        P('It explains what fit looks like but says little about how an organization moves from misfit to fit, or what that transition costs.',
          '它解释了匹配是什么样子，却几乎没说组织如何从失配走向匹配，以及这一转变的代价。'),
        P('The framework has been criticized as functionalist: it assumes surviving organizations are fitted, which makes misfit hard to observe and the claim hard to disconfirm.',
          '该框架被批评为功能主义：它假定存活的组织即是匹配的，这使失配难以观察、主张难以证伪。'),
      ],
      empirical=[
        P('Studies routinely test a moderation form while stating a profile argument, so the statistical model does not match the theoretical claim being made.',
          '研究常在陈述剖面式论证的同时检验调节形式，统计模型与所提出的理论主张并不对应。'),
        P('Contingencies are measured at one point in time while structure reflects accumulated history, so the fit being tested may never have coexisted.',
          '权变因素在单一时点测量，结构却反映累积的历史，因此被检验的"匹配"可能从未真正同时存在过。'),
      ],
      temporal=[
        P('The framework assumes structure is a durable choice adjusted infrequently, which is why misfit could persist long enough to damage performance. Where reporting lines, teams, and processes are reconfigured continuously, structure is closer to a flow than a state, and a cross-sectional fit measure describes a moment rather than a condition.',
          '框架假定结构是不常调整的持久选择，因此失配才能持续到足以损害绩效。当汇报线、团队与流程被持续重构时，结构更接近一种流动而非状态，横截面的匹配指标描述的只是一个瞬间而非一种状况。'),
        P('Technology entered the theory as a property of the production process that shaped the structure around it. Where the same software supports many organizational forms, technology constrains structure far less than the original studies of manufacturing found.',
          '技术作为生产过程的属性进入理论，塑造着围绕它的结构。当同一套软件可以支撑多种组织形态时，技术对结构的约束远小于当年制造业研究所发现的程度。'),
      ],
      today=[
        P('State the form of fit and test that form. A product term does not test a configurational argument, and reporting one as the other is the most common error in this literature.',
          '应说明匹配的形式并检验该形式。乘积项不检验配置式论证，把二者混同是这一文献中最常见的错误。'),
        P('It remains the right frame whenever the claim is that a practice works in some conditions and not others, which is most practical management questions.',
          '只要主张是"某做法在某些条件下有效、在另一些条件下无效"，它就仍是恰当的框架——而多数实务管理问题正属此类。'),
      ]),
])
