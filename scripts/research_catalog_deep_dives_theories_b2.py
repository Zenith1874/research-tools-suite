# -*- coding: utf-8 -*-
"""Deep dives for catalog theories, batch 2.

Six theories that are heavily cited in the corpus and were carrying only the
short catalog record: institutional logics, stakeholder theory, the
knowledge-based view, organizational support theory, leader-member exchange,
and the theory of planned behavior.

Schema helpers live in ``research_catalog_deep_dives``.
"""

from research_catalog_deep_dives import D, Debate, P, Pos

THEORY_DIVES_B2 = dict([

    # ------------------------------------------------------ institutional logics
    D('institutional-logics',
      era='Named in 1991 and developed into a research programme from 1999; dominant in field-level organizational research through the 2010s.',
      era_zh='1991 年提出，1999 年起发展为研究纲领，2010 年代成为场域层面组织研究的主流。',
      situation=[
        P('Institutional theory had explained conformity well: organizations in a field converge because legitimacy requires it. What it explained poorly was variation, change, and organizations that persistently do not conform.',
          '制度理论把"顺从"解释得很好：场域内的组织趋同，因为合法性要求如此。它解释不好的是差异、变迁，以及那些持续不顺从的组织。'),
        P('If a field imposes one set of expectations, deviation is deviance. The logics perspective changed the premise: fields carry several belief systems at once, and what looks like deviance may be conformity to a different logic.',
          '若场域只施加一套期待，偏离即是越轨。逻辑视角改变了这一前提：场域同时承载多套信念体系，看似越轨的行为，可能只是顺从了另一套逻辑。'),
      ],
      argument=[
        P('An institutional logic is a socially constructed set of assumptions, values, and rules that tells actors what goals are legitimate, what counts as evidence, and who has authority. Logics come from societal orders such as market, state, profession, family, and religion.',
          '制度逻辑是一套社会建构的假定、价值与规则，它告诉行动者哪些目标是正当的、什么算作证据、谁拥有权威。逻辑源自市场、国家、专业、家庭、宗教等社会秩序。'),
        P('Because multiple logics are available in most fields, actors have material for agency: they can draw on one logic to justify departing from another. This is how the perspective restores the agency that early institutional theory lacked.',
          '由于多数场域中存在多套可用逻辑，行动者因而具备能动性的材料：可以援引一套逻辑来为偏离另一套辩护。这正是该视角恢复早期制度理论所缺能动性的方式。'),
        P('Hybrid organizations, which must satisfy two logics at once, become the natural site for studying the mechanism, since the tension there is visible rather than latent.',
          '必须同时满足两套逻辑的混合型组织，因而成为研究该机制的天然场所——那里的张力是显性的而非潜在的。'),
      ],
      development=[
        P('Work on logic blending, compartmentalizing, and sequencing described how organizations hold conflicting logics without resolving them, which connects this literature to paradox theory.',
          '关于逻辑融合、区隔与轮替的研究，描述了组织如何在不消解冲突的情况下同时持有多套逻辑，这把该文献与悖论理论连接起来。'),
      ],
      debates=[
        Debate('How many logics are there and who decides?', '逻辑有多少种，由谁来定？',
               [Pos('Ideal-type position',
                    'A small set of societal orders provides a shared vocabulary that makes findings comparable across studies.',
                    '一小组社会秩序提供了共享词汇，使跨研究的发现得以比较。'),
                Pos('Inductive position',
                    'Logics should be derived from the field under study; imposing a fixed typology forces the data into categories that may not fit it.',
                    '逻辑应从所研究的场域中归纳得出；强加固定类型学会把数据塞进未必适配的类别。')],
               'Open. In practice the number and boundaries of logics vary by study, which is the main obstacle to accumulating evidence.',
               '未决。实践中逻辑的数量与边界因研究而异，这正是证据难以累积的主要障碍。'),
      ],
      theoretical=[
        P('Which logic is operating is usually established by researcher interpretation of what actors say and do, and an alternative reading is rarely tested against the same material.',
          '"哪套逻辑在起作用"通常由研究者对行动者言行的解读来确立，而很少用同一材料检验另一种解读。'),
        P('The perspective explains why several outcomes are possible better than it predicts which one will occur, which limits it to explanation after the fact.',
          '该视角对"为何多种结果都可能"的解释，强于对"哪一种会发生"的预测，因而基本只能事后解释。'),
      ],
      empirical=[
        P('Logics are inferred from discourse — documents, interviews, public statements — so a study may be measuring how an organization talks rather than how it decides.',
          '逻辑是从话语中推断的——文档、访谈、公开声明——因此研究可能测的是组织如何说话，而非如何决策。'),
        P('Because hybrid organizations are the preferred site, the evidence base overrepresents settings where logic conflict is unusually visible.',
          '由于混合型组织是首选研究场所，证据基础过度代表了"逻辑冲突异常可见"的情境。'),
      ],
      temporal=[
        P('The societal orders were specified for a world in which market, state, profession, and family were the salient sources of authority. Platform governance is not obviously reducible to any of them: a platform sets rules like a state, prices like a market, and certifies like a profession, and the typology has no slot for it.',
          '社会秩序的界定针对的是"市场、国家、专业、家庭"为主要权威来源的世界。平台治理并不能明显归入其中任何一种：平台像国家一样立规、像市场一样定价、像专业一样认证，而类型学中没有它的位置。'),
        P('The perspective assumes logics are carried by people and institutions and transmitted through socialization. Where decision rules are embedded in software that no participant can inspect, a logic can operate without anyone articulating it, which the discourse-based method cannot detect.',
          '该视角假定逻辑由人与制度承载、经由社会化传递。当决策规则嵌入无人可检视的软件时，逻辑可以在无人言说的情况下运作——而基于话语的方法无法侦测到它。'),
      ],
      today=[
        P('Derive the logics from the field and show the material that supports each attribution. A study that names logics without showing how they were identified cannot be evaluated.',
          '应从场域中归纳逻辑，并展示支持每项归因的材料。只命名逻辑而不说明如何识别的研究，无法被评估。'),
        P('It is a strong lens for sustainability, healthcare, social enterprise, and platform governance, where genuinely incompatible demands coexist and neither can simply win.',
          '在可持续、医疗、社会企业与平台治理等确实存在不相容要求、且任何一方都无法单方胜出的领域，它是有力的视角。'),
      ]),

    # -------------------------------------------------------- stakeholder theory
    D('stakeholder-theory',
      era='Proposed in 1984; given a salience model in 1997 and a normative restatement through the 2000s.',
      era_zh='1984 年提出，1997 年获得显著性模型，2000 年代完成规范性重述。',
      situation=[
        P('The prevailing account held that managers owe their duty to shareholders and that maximizing share value is both the objective and the discipline. That framing left no principled way to handle obligations to employees, customers, suppliers, and communities except as constraints.',
          '当时的主流观点认为管理者的责任归于股东，股东价值最大化既是目标也是约束机制。该框定使得对员工、顾客、供应商与社区的义务，除了作为约束条件之外无从安置。'),
        P('Stakeholder theory reframed the firm as a set of relationships with parties who affect or are affected by it, and argued that managing those relationships is the job rather than a distraction from it.',
          '利益相关者理论把企业重新框定为"与影响它或被它影响的各方"之间的一组关系，并主张经营这些关系本身就是管理工作，而非对它的干扰。'),
      ],
      argument=[
        P('The descriptive claim is that firms do have stakeholders and that their relationships shape outcomes. The instrumental claim is that managing them well produces better performance. The normative claim is that stakeholders have legitimate interests independent of whether attending to them pays.',
          '描述性主张是：企业确实存在利益相关者，且这些关系塑造结果。工具性主张是：妥善经营这些关系能带来更好绩效。规范性主张是：无论是否划算，利益相关者的利益本身就具有正当性。'),
        P('The three claims are frequently conflated. An instrumental finding that stakeholder management pays does not establish the normative claim, and the normative claim does not require the instrumental one to hold.',
          '三类主张常被混为一谈。"利益相关者管理有回报"的工具性发现无法确立规范性主张；规范性主张也不以工具性主张成立为前提。'),
        P('Salience supplies the practical rule: which stakeholders get attention depends on their power, the legitimacy of their claim, and its urgency, and salience shifts as those change.',
          '显著性提供了实践规则：哪些利益相关者获得关注，取决于其权力、诉求的正当性与紧迫性；三者变化，显著性随之改变。'),
      ],
      development=[
        P('Empirical work largely reduced the theory to corporate social performance ratings, which made large-sample tests possible while discarding the relational core the theory was built on.',
          '经验研究在很大程度上把该理论化约为企业社会绩效评级，这使大样本检验成为可能，却丢弃了理论赖以建立的关系性内核。'),
      ],
      debates=[
        Debate('Can the theory guide a decision when stakeholders conflict?', '当利益相关者冲突时，该理论能指导决策吗？',
               [Pos('Critique',
                    'Without a rule for trading off competing claims, "balance stakeholder interests" gives managers latitude to justify almost any decision after the fact.',
                    '若没有权衡相互冲突诉求的规则，"平衡各方利益"给了管理者事后为几乎任何决策辩护的空间。'),
                Pos('Defence',
                    'The theory supplies criteria — power, legitimacy, urgency — and the absence of a mechanical rule reflects that these are genuinely judgement problems.',
                    '理论提供了标准——权力、正当性、紧迫性——而缺少机械规则，恰恰反映这些本就是判断问题。')],
               'Open, and it is the main reason critics call the theory unfalsifiable as a management prescription.',
               '未决，这也是批评者称其作为管理处方不可证伪的主要理由。'),
      ],
      theoretical=[
        P('Who counts as a stakeholder is not settled. A definition broad enough to include everyone affected makes the category unusable; one narrow enough to be operational reintroduces the exclusions the theory objected to.',
          '"谁算利益相关者"没有定论。宽到涵盖所有受影响者，类别就无法使用；窄到可操作，又重新引入了该理论所反对的排斥。'),
        P('The three claims rest on different kinds of argument — empirical, instrumental, and ethical — and evidence for one is routinely presented as support for the others.',
          '三类主张依赖不同性质的论证——经验的、工具的、伦理的——而对其中一类的证据常被当作对其他两类的支持。'),
      ],
      empirical=[
        P('Corporate social performance ratings from different providers correlate only moderately with each other, so a study finding depends substantially on which rating it used.',
          '不同供应商的企业社会绩效评级彼此相关只是中等，因此研究结论在很大程度上取决于用了哪一家评级。'),
        P('Firms that score well on stakeholder measures also tend to be larger, more profitable, and more visible, and disentangling the direction of that relationship requires a design most studies do not have.',
          '在利益相关者指标上得分高的企业往往也更大、更盈利、更受关注；理清这一关系的方向需要多数研究并不具备的设计。'),
      ],
      temporal=[
        P('The framework assumes stakeholders are identifiable groups that can be enumerated and engaged. Where a firm affects diffuse populations through data, recommendation, or environmental externality, the affected party may not know it is one, and salience based on power and urgency systematically excludes those who cannot organize.',
          '框架假定利益相关者是可枚举、可接触的可辨识群体。当企业通过数据、推荐或环境外部性影响弥散人群时，受影响者可能并不知道自己是利益相关者；而基于权力与紧迫性的显著性，会系统性排除那些无法组织起来的人。'),
        P('It was written when a firm boundary determined who was affected. Platform and supply-chain arrangements distribute effects across parties the firm has no relationship with, which the relational core of the theory does not reach.',
          '它写作之时，企业边界决定了谁受影响。平台与供应链安排把影响扩散到企业与之没有关系的各方，而理论的关系性内核触及不到这些人。'),
      ],
      today=[
        P('Say which of the three claims the study is making. Most confusion in this literature comes from testing the instrumental claim and concluding about the normative one.',
          '应说明研究提出的是三类主张中的哪一类。这一文献中的多数混乱，来自检验工具性主张却对规范性主张下结论。'),
        P('If the design uses a social performance rating, report which one and check whether the result survives an alternative rating. It frequently does not.',
          '若设计使用社会绩效评级，应报告用的是哪一家，并检验结论在换用另一家评级后是否依然成立——它经常不成立。'),
      ]),

    # ---------------------------------------------------- knowledge-based view
    D('knowledge-based-view',
      era='Articulated in 1992 and 1996 as an extension of the resource-based view; heavily applied to alliances and innovation through the 2000s.',
      era_zh='1992 与 1996 年作为资源基础观的延伸提出，2000 年代被大量应用于联盟与创新研究。',
      situation=[
        P('The resource-based view established that heterogeneous resources explain persistent advantage but treated resources as a general category. If some resources matter more than others, the question is which, and why.',
          '资源基础观确立了异质资源解释持续优势，却把资源当作一个笼统类别。若某些资源比另一些更重要，问题就是：哪些，以及为什么。'),
        P('The answer offered was knowledge, on the argument that it is the resource least amenable to purchase and imitation, and that the firm exists precisely because it integrates specialized knowledge better than a market can.',
          '给出的答案是知识：它是最难以购买与模仿的资源；企业之所以存在，正因为它比市场更善于整合分散的专业化知识。'),
      ],
      argument=[
        P('Production requires specialized knowledge held by many individuals. Because that knowledge is costly to transfer and cannot be fully articulated, coordinating it through market contracts is expensive, and the firm is the efficient integrating structure.',
          '生产需要由众多个体持有的专业化知识。由于这些知识转移成本高、无法被完全言明，通过市场契约来协调它代价高昂，企业因而成为高效的整合结构。'),
        P('Tacitness is the load-bearing assumption. If knowledge could be fully codified it could be sold, and both the advantage and the rationale for the firm would disappear.',
          '默会性是承重假定。若知识能被完全编码，它就可以被出售，优势与企业存在的理由都将随之消失。'),
        P('The strategic implication is that advantage comes from integration capability rather than from knowledge volume; a firm that knows a great deal but cannot combine it holds no advantage.',
          '其战略含义是：优势来自整合能力而非知识存量；知道很多却无法组合的企业并不拥有优势。'),
      ],
      development=[
        P('Absorptive capacity supplied the complementary account of acquiring external knowledge, and the two are frequently used together, though they answer different questions.',
          '吸收能力提供了获取外部知识的互补解释，二者常被并用，尽管它们回答的是不同问题。'),
      ],
      debates=[
        Debate('Is it a distinct theory or a specialization of the resource-based view?', '它是独立理论还是资源基础观的特例？',
               [Pos('Distinctness position',
                    'It derives the existence and boundaries of the firm from knowledge integration, which the resource-based view does not attempt.',
                    '它由知识整合推导出企业的存在与边界，而资源基础观并不尝试这一点。'),
                Pos('Specialization position',
                    'Knowledge is one resource among several, and the VRIN logic already covers why it would be hard to imitate.',
                    '知识只是诸多资源之一，而 VRIN 逻辑已经涵盖了它为何难以模仿。')],
               'Unresolved, and the answer determines whether the theory has independent predictions to test.',
               '未决，而答案决定了该理论是否拥有可供检验的独立预测。'),
      ],
      theoretical=[
        P('Tacitness is asserted more often than demonstrated. Whether a given body of knowledge is genuinely hard to codify is an empirical question that the theory usually assumes away.',
          '默会性被断言的次数多于被证明的次数。某类知识是否确实难以编码，是理论通常直接假定掉的经验问题。'),
        P('Knowledge is treated as an asset the firm holds, which sits awkwardly with the observation that it resides in people who can leave.',
          '知识被当作企业持有的资产，这与"知识存在于可以离职的人身上"这一观察颇为扞格。'),
      ],
      empirical=[
        P('Knowledge is proxied by patents, R&D spend, or education levels, all of which capture the codified and measurable part — precisely the part the theory says is not the source of advantage.',
          '知识被专利、研发支出或学历水平代理，而它们捕捉的都是可编码、可测量的部分——恰恰是理论所说"并非优势来源"的那部分。'),
        P('Integration capability, the theory central construct, is rarely measured at all; studies infer it from the outcome it is meant to explain.',
          '整合能力这一理论核心构念几乎从未被测量；研究是从它本应解释的结果反推出来的。'),
      ],
      temporal=[
        P('The tacitness premise was formulated when transferring know-how meant moving people or lengthy apprenticeship. Where a substantial part of applied knowledge can be encoded in a model, a prompt, or a pipeline and copied at near-zero cost, the mechanism generating the advantage is weaker than when the theory was written.',
          '默会性前提成形之时，转移诀窍意味着调动人员或长期学徒。当相当一部分应用知识可以被编码进模型、提示或流水线并以近乎零成本复制时，产生优势的机制已弱于该理论写作之时。'),
        P('It assumes the integrating structure is the firm. Open-source development, ecosystems, and shared foundation models integrate specialized knowledge across firm boundaries, which the argument for the firm existence does not accommodate.',
          '它假定整合结构就是企业。开源开发、生态系统与共享基础模型跨越企业边界整合专业化知识，而"企业为何存在"的论证无法容纳这一点。'),
      ],
      today=[
        P('If the study invokes tacitness, show it rather than assuming it. What cannot be written down, and what evidence supports that, is the empirical core of the claim.',
          '若研究援引默会性，应予以证明而非假定。什么无法被写下、有何证据支持，才是该主张的经验内核。'),
        P('Measure integration rather than stock. A count of patents tests the resource-based view, not this one.',
          '应测量整合而非存量。专利计数检验的是资源基础观，不是这个理论。'),
      ]),

    # -------------------------------------------- organizational support theory
    D('organizational-support-theory',
      era='Introduced in 1986; consolidated by meta-analysis in 2017 after three decades of accumulation.',
      era_zh='1986 年提出，历经三十年累积后于 2017 年由元分析加以整合。',
      situation=[
        P('Research had established that organizations evaluate employees continuously. The reverse question had no framework: employees also form a judgement about the organization, and that judgement should shape what they give back.',
          '研究已确立组织在持续评价员工。反向的问题却没有框架：员工同样在对组织形成判断，而这一判断应当影响他们的回报。'),
        P('Social exchange supplied the mechanism, and the contribution was to specify the employee side of the exchange as a single global belief that could be measured and predicted.',
          '社会交换提供了机制，而该理论的贡献在于把交换的员工一侧界定为一个可测量、可预测的整体信念。'),
      ],
      argument=[
        P('Employees personify the organization and form a global belief about how far it values their contributions and cares about their wellbeing. That belief is perceived organizational support.',
          '员工把组织人格化，并形成"组织在多大程度上重视我的贡献、关心我的福祉"的整体信念。这一信念即组织支持感。'),
        P('Support generates felt obligation to help the organization reach its goals, and it also meets socioemotional needs, which increases identification and affective attachment. Both paths lead to effort and retention.',
          '支持感产生"帮助组织达成目标"的义务感，同时满足社会情感需要，从而提高认同与情感依附。两条路径都通向努力与留任。'),
        P('The critical qualifier is discretion. Support attributed to the organization free choice counts; the same benefit provided because law or a union contract requires it does not generate the same obligation.',
          '关键限定条件是自主性。被归因于组织自主选择的支持才算数；同样的待遇若因法律或工会合同所迫，则不会产生同等的义务感。'),
      ],
      development=[
        P('Perceived supervisor support was separated from organizational support, with evidence that supervisor support partly transfers to the organization when the supervisor is seen as representing it.',
          '主管支持感与组织支持感被区分开，证据显示：当主管被视为组织代表时，主管支持会部分转移为组织支持。'),
      ],
      debates=[
        Debate('Is perceived organizational support distinct from affective commitment?', '组织支持感与情感承诺可区分吗？',
               [Pos('Distinctness position',
                    'Support is a belief about what the organization does; commitment is an attachment to it. Support is theorized as the cause of commitment, not the same thing.',
                    '支持感是关于"组织做了什么"的信念，承诺是对组织的依附。理论上支持感是承诺的原因，而非同一事物。'),
                Pos('Redundancy critique',
                    'The two scales correlate highly and are measured in the same survey, so the causal ordering is imposed by the model rather than shown.',
                    '两个量表高度相关且在同一份问卷中测量，因果顺序是由模型强加的，而非被证明的。')],
               'The conceptual distinction is accepted; the measurement problem is not solved.',
               '概念区分已被接受，测量问题尚未解决。'),
      ],
      theoretical=[
        P('Personification of the organization is assumed rather than examined. Which agent an employee treats as the organization — the immediate manager, HR, senior leadership — is left open and probably varies.',
          '组织的人格化被假定而非被考察。员工把谁当作"组织"——直属经理、人力资源、高层——被搁置未论，而这很可能因人而异。'),
        P('The discretion qualifier is central but rarely modelled; most studies measure support without asking whether the employee saw it as freely given.',
          '自主性这一限定条件很关键，却很少被建模；多数研究只测量支持，不追问员工是否认为它是自愿给予的。'),
      ],
      empirical=[
        P('Almost the entire literature is single-source, single-wave self-report, so the theory central mediation through felt obligation is supported by cross-sectional association.',
          '几乎整个文献都是单源、单波次自评，因此理论核心的"义务感中介"只由横截面关联支持。'),
        P('The full scale and its short forms are used interchangeably, and results are compared across studies using instruments of different length without adjustment.',
          '完整量表与其简版被混用，不同长度工具的研究结果未经调整即被相互比较。'),
      ],
      temporal=[
        P('The theory assumes the organization acts through visible human agents whose choices employees can attribute to organizational intent. Where benefits, schedules, and evaluations are delivered by a system, there may be no agent to attribute discretion to, and the mechanism that converts support into obligation has no clear target.',
          '理论假定组织通过可见的人类代理行事，员工能把其选择归因于组织意图。当福利、排班与评价由系统交付时，可能不存在可归因自主性的代理人，而"把支持转化为义务"的机制也就失去了明确对象。'),
        P('It was formulated for continuing full-time employment where the exchange had time to develop. Short-tenure, contract, and platform arrangements compress that horizon, and a global belief about organizational care may not form at all.',
          '它针对的是有时间让交换关系发展的持续全职雇佣。短任期、合约与平台安排压缩了这一时间跨度，"组织是否关心我"的整体信念可能根本不会形成。'),
      ],
      today=[
        P('Measure the discretion attribution alongside support. Without it the study cannot distinguish a generous employer from one that is merely compliant with the law.',
          '应在测量支持的同时测量自主性归因。缺少它，研究无法区分慷慨的雇主与只是守法的雇主。'),
        P('In algorithmic or platform settings, ask who the employee thinks is providing the support before assuming the organization is the referent.',
          '在算法或平台情境中，应先询问员工认为支持来自谁，再假定组织就是指称对象。'),
      ]),

    # ----------------------------------------------------- leader-member exchange
    D('leader-member-exchange',
      era='Introduced as vertical dyad linkage in 1975; reviewed and consolidated as LMX in 1995.',
      era_zh='1975 年以"垂直二元联结"提出，1995 年以 LMX 之名被综述并整合。',
      situation=[
        P('Leadership research assumed a leader has a style applied consistently to subordinates. Observation contradicted it: the same manager behaved very differently toward different people on the same team.',
          '领导研究曾假定领导者拥有一种对下属一致施用的风格。观察与之矛盾：同一位管理者对同一团队中的不同成员，行为差异很大。'),
        P('If the style is not constant across subordinates, then the unit of analysis cannot be the leader. It has to be the relationship, and that was the shift the theory made.',
          '若风格在下属之间并不恒定，分析单位就不能是领导者，而必须是关系——这正是该理论所作的转变。'),
      ],
      argument=[
        P('Leaders develop exchange relationships of differing quality with each subordinate through a role-making process: an offer of extra responsibility, a response, and reciprocation that either builds the relationship or leaves it transactional.',
          '领导者通过角色形成过程与每位下属发展出质量不同的交换关系：给出额外责任、对方作出回应、再以互惠使关系或者深化、或者停留在交易层面。'),
        P('High-quality relationships involve trust, latitude, and mutual obligation beyond the employment contract; low-quality ones stay within it. Relationship quality, not leader style, predicts follower attitudes and behaviour.',
          '高质量关系包含超出雇佣契约的信任、自由度与相互义务；低质量关系则停留在契约之内。预测下属态度与行为的是关系质量，而非领导风格。'),
        P('Differentiation within a team is therefore expected rather than a failure of fairness, though whether it helps or harms depends on how members judge its basis.',
          '因此团队内部的差异化是预期之中的，而非公平性的失败；但它是助益还是损害，取决于成员如何看待其依据。'),
      ],
      development=[
        P('Attention moved from the dyad to the team, asking how the distribution of relationship quality across a group affects climate, comparison, and performance.',
          '关注点从二元关系转向团队，追问关系质量在群体中的分布如何影响氛围、比较与绩效。'),
      ],
      debates=[
        Debate('Whose report measures the relationship?', '谁的报告才是对关系的测量？',
               [Pos('Follower-report practice',
                    'Follower perception is what drives follower behaviour, so the follower report is the causally relevant measure.',
                    '驱动下属行为的是下属的感知，因此下属报告才是因果相关的测量。'),
                Pos('Dyadic critique',
                    'Leader and follower reports of the same relationship correlate only modestly, which means one of them is not measuring the shared relationship the theory posits.',
                    '领导与下属对同一关系的报告相关只是中等，这意味着至少有一方并未测到理论所设定的那个"共享关系"。')],
               'Open. The modest agreement is a persistent finding that the theory has not fully absorbed.',
               '未决。这一中等一致性是持续存在的发现，理论尚未充分吸收它。'),
      ],
      theoretical=[
        P('The construct overlaps heavily with perceived supervisor support and trust in the leader, and studies rarely establish that it adds explanatory power beyond them.',
          '该构念与主管支持感、对领导的信任高度重叠，而研究很少证明它相对于二者具有增量解释力。'),
        P('Whether the relationship is a shared property of the dyad or two separate perceptions is unresolved, and the two readings imply different measurement models.',
          '关系究竟是二元共享的属性，还是两个各自独立的感知，尚未定论；两种读法意味着不同的测量模型。'),
      ],
      empirical=[
        P('Follower-reported LMX and follower-reported outcomes come from the same survey, which is the standard design and the standard limitation.',
          '下属自报的 LMX 与下属自报的结果来自同一份问卷，这既是标准设计，也是标准局限。'),
        P('Team-level differentiation is often computed as the variance of follower reports, which confounds genuine differentiation with disagreement about the same relationships.',
          '团队层面的差异化常以下属报告的方差计算，这把真实的差异化与"对同一关系的分歧"混在一起。'),
      ],
      temporal=[
        P('The theory assumes a supervisor with discretion to allocate opportunity, latitude, and attention. Where assignment and evaluation are performed by a system, the resource the leader trades in the role-making process is substantially reduced, and the relationship may have little to be built on.',
          '理论假定主管拥有分配机会、自由度与关注的裁量权。当派单与评价由系统执行时，领导者在角色形成过程中可交换的资源大幅减少，关系可能失去赖以建立的基础。'),
        P('Role making was theorized through repeated informal interaction. Remote and hybrid arrangements reduce unplanned contact, which is the channel through which the relationship was assumed to develop, so the same LMX score may reflect a different process than it did originally.',
          '角色形成被设想为经由反复的非正式互动。远程与混合安排减少了计划外接触，而关系原本被假定正是经由这一渠道发展的；因此同样的 LMX 分数所反映的过程，可能已与原初不同。'),
      ],
      today=[
        P('Justify what LMX adds beyond supervisor support and trust, or use one of those instead. Adding a fourth overlapping scale to a model is not a contribution.',
          '应论证 LMX 相对于主管支持与信任的增量，否则不如直接使用后者。在模型中再加一个重叠量表并不构成贡献。'),
        P('Collect both sides of the dyad where possible, and report the disagreement rather than averaging it away. The gap is often the most informative part of the data.',
          '尽可能收集二元关系的双方报告，并报告其分歧而非将其平均掉。这一差距往往是数据中最有信息量的部分。'),
      ]),

    # ------------------------------------------------- theory of planned behavior
    D('theory-of-planned-behavior',
      era='Extended from the theory of reasoned action in 1991; among the most cited behavioural frameworks and increasingly challenged from the 2010s.',
      era_zh='1991 年由理性行动理论扩展而来，是被引用最多的行为框架之一，2010 年代起受到越来越多挑战。',
      situation=[
        P('The predecessor theory predicted behaviour from attitude and social norm, which worked for behaviours people could simply choose to perform. It failed where performance depended on resources, skill, or opportunity the person might lack.',
          '前身理论以态度与社会规范预测行为，对"想做就能做"的行为有效；一旦行为的实施依赖个体可能缺乏的资源、技能或机会，它就失效了。'),
        P('The extension added perceived behavioural control to cover exactly those cases, giving the framework a way to represent the difference between wanting to act and being able to.',
          '该扩展加入感知行为控制以覆盖这类情形，使框架能够表达"想做"与"能做"之间的差别。'),
      ],
      argument=[
        P('Attitude toward the behaviour, subjective norm, and perceived behavioural control jointly form an intention. Intention, together with actual control, predicts behaviour.',
          '对行为的态度、主观规范与感知行为控制共同形成行为意向；意向连同实际控制预测行为。'),
        P('Perceived control does double duty: it feeds intention and also predicts behaviour directly, on the reasoning that a person with control can act on an intention that someone without it cannot.',
          '感知控制承担双重作用：既进入意向，也直接预测行为——理由是有控制力的人能把意向付诸实施，而没有控制力的人不能。'),
        P('Each determinant rests on underlying beliefs — behavioural, normative, and control — which is where an intervention is supposed to act. Interventions that target intention directly, without changing beliefs, have little to work with.',
          '每个决定因素都建立在底层信念之上——行为信念、规范信念、控制信念——干预本应作用于此。直接针对意向而不改变信念的干预，几乎无从着力。'),
      ],
      development=[
        P('The framework was extended in hundreds of studies by adding constructs — habit, moral norm, self-identity, anticipated regret — each raising explained variance in intention while leaving the intention-behaviour gap intact.',
          '该框架在数百项研究中被不断扩展——习惯、道德规范、自我认同、预期后悔——每次都提高了意向的解释方差，却未触动意向与行为之间的缺口。'),
      ],
      debates=[
        Debate('Has the intention-behaviour gap been resolved?', '意向—行为缺口解决了吗？',
               [Pos('Framework position',
                    'Intention is the best available single predictor, and the gap narrows when intention is measured specifically and close in time to the behaviour.',
                    '意向是现有最好的单一预测变量；当意向被具体测量且与行为时间接近时，缺口会缩小。'),
                Pos('Critical position',
                    'Meta-analytic evidence shows large changes in intention produce much smaller changes in behaviour, which is a problem for a theory whose central path runs through intention.',
                    '元分析证据显示意向的大幅变化只带来行为的小幅变化，这对一个核心路径经由意向的理论构成问题。')],
               'Open and consequential. It is the main reason the framework is now often used as a baseline rather than as the contribution.',
               '未决且后果重大。这正是该框架如今常被用作基线而非贡献本身的主要原因。'),
      ],
      theoretical=[
        P('It models deliberative choice. Habitual, automatic, and affect-driven behaviour is outside the framework, and much of what it is applied to — consumption, health, compliance — is substantially habitual.',
          '它建模的是审慎选择。习惯性、自动化与情绪驱动的行为在框架之外，而它被应用的许多领域——消费、健康、合规——在很大程度上正是习惯性的。'),
        P('Perceived behavioural control and self-efficacy are difficult to distinguish empirically, and studies use the two labels for similar items.',
          '感知行为控制与自我效能在经验上难以区分，不同研究用这两个标签指称相似的题项。'),
      ],
      empirical=[
        P('Most tests measure intention and behaviour by self-report in the same instrument, which inflates the intention-behaviour relationship that is the framework central claim.',
          '多数检验以同一工具自评测量意向与行为，这抬高了作为框架核心主张的"意向—行为"关系。'),
        P('Adding a construct to raise explained variance in intention is easy and has been done many times; explaining behaviour rather than intention is where the framework performs weakly.',
          '增加变量以提高意向的解释方差既容易又已被反复实施；而在解释行为（而非意向）上，该框架表现薄弱。'),
      ],
      temporal=[
        P('The framework assumes behaviour follows from a considered intention formed in advance. Choice architectures that set defaults, order options, and prompt at the moment of decision produce behaviour without a prior intention, and a model built on intention has little to predict there.',
          '框架假定行为源于事先形成的深思意向。设定默认项、排列选项、在决策瞬间给出提示的选择架构，会在没有先行意向的情况下产生行为——建立在意向之上的模型在那里几乎无从预测。'),
        P('Subjective norm was operationalized as what important others think the person should do. Where norms are inferred from visible aggregate behaviour on platforms rather than from known referents, the construct as measured no longer corresponds to the mechanism as theorized.',
          '主观规范被操作化为"重要他人认为我应当如何"。当规范是从平台上可见的群体行为推断而来、而非来自已知的参照他人时，被测量的构念已不再对应理论所设定的机制。'),
      ],
      today=[
        P('Use it as a baseline and measure behaviour independently of the person reporting the intention. A study that predicts self-reported behaviour from self-reported intention has not tested the gap that matters.',
          '应把它当作基线，并独立于报告意向者来测量行为。以自评意向预测自评行为的研究，并未检验真正重要的那个缺口。'),
        P('If the behaviour is habitual or shaped by a choice architecture, say so and model that mechanism rather than adding another predictor of intention.',
          '若行为是习惯性的或被选择架构塑造，应明确说明并对该机制建模，而不是再给意向增加一个预测变量。'),
      ]),
])
