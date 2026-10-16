# -*- coding: utf-8 -*-
"""Deep dives for catalog constructs, batch 2.

Selected by observed use in the A* cache: uncertainty, status, organizational
identification, capital structure, and interdependence are among the most
frequently appearing constructs in the corpus and had only a one-line record.

Schema helpers live in ``research_catalog_deep_dives``; see the batch-1
construct module for the question set these blocks answer.
"""

from research_catalog_deep_dives import D, Debate, P, Pos

CONSTRUCT_DIVES_B2 = dict([

    # ------------------------------------------------------------- uncertainty
    D('uncertainty',
      era='Separated from risk in 1921; operationalized in organization theory from the 1960s and still measured inconsistently.',
      era_zh='1921 年与风险区分开，1960 年代起在组织理论中被操作化，至今测量仍不一致。',
      situation=[
        P('Economics had treated unknown outcomes as risk: a known list of states with known probabilities. That framing made decisions tractable but described a situation decision makers rarely face.',
          '经济学此前把未知结果处理为风险：状态清单已知、概率已知。这一框定使决策易于处理，却描述了决策者很少真正面对的情形。'),
        P('The separation that mattered was between risk, where probabilities are known, and uncertainty, where they are not — and organization theory later added a third case where even the list of possible states is unknown.',
          '关键的区分在于：风险的概率已知，不确定性的概率未知；组织理论后来又补上第三种情形——连可能状态的清单本身都未知。'),
      ],
      argument=[
        P('The construct is used at two different levels that share a name. Environmental uncertainty is a property of the situation: how variable and unpredictable the setting is. Perceived uncertainty is a property of the person: how unable they feel to predict it.',
          '该构念在两个不同层面上共用一个名字。环境不确定性是情境的属性：环境有多易变、多难预测；感知不确定性是个体的属性：个体在多大程度上感到无法预测它。'),
        P('These do not have to move together, and much of the inconsistency in this literature comes from a theory stated at one level being tested with a measure from the other.',
          '二者不必同向变动；这一文献中大量的不一致，正来自"理论陈述在一个层面、测量却取自另一个层面"。'),
        P('A further distinction separates state uncertainty about what the environment will do, effect uncertainty about how it will affect the organization, and response uncertainty about what options exist and what they will produce. They have different antecedents and different remedies.',
          '进一步的区分是：状态不确定性关乎环境会如何变化，效应不确定性关乎环境会如何影响本组织，反应不确定性关乎有哪些选项、各自会带来什么。三者前因不同，应对方式也不同。'),
      ],
      development=[
        P('Strategy adopted environmental dynamism as an archival proxy, computed from the volatility of industry sales or similar series, which made large-sample work possible at the cost of collapsing the three types into one number.',
          '战略研究采用环境动态性作为档案代理，由行业销售额等序列的波动率计算而来。这使大样本研究成为可能，代价是把三种类型压成一个数字。'),
      ],
      debates=[
        Debate('Should uncertainty be measured objectively or perceptually?', '不确定性应当客观测量还是主观测量？',
               [Pos('Objective position',
                    'Archival volatility measures are comparable across firms and immune to the respondent bias that perception measures carry.',
                    '档案波动率指标跨企业可比，且不受感知测量所带的受访者偏差影响。'),
                Pos('Perceptual position',
                    'Decisions respond to what managers believe, not to a volatility statistic they never see, so the perceptual measure is the causally relevant one.',
                    '决策回应的是管理者的信念，而非他们从未见过的波动率统计量，因此感知测量才是因果相关的那一个。')],
               'Open. The pragmatic reading is that they answer different questions and should not be substituted for one another.',
               '未决。务实的读法是：二者回答不同问题，不应相互替代。'),
      ],
      theoretical=[
        P('Uncertainty and ambiguity are routinely conflated. Uncertainty is not knowing which state will occur; ambiguity is not knowing what the states mean or how to frame them, and they call for different responses.',
          '不确定性与模糊性常被混为一谈。不确定性是不知道哪种状态会发生；模糊性是不知道这些状态意味着什么、该如何框定——二者所需的应对不同。'),
        P('More uncertainty is treated as monotonically worse in most models, though moderate uncertainty is what creates the option value and the entrepreneurial opportunity other frameworks depend on.',
          '多数模型把不确定性视为越高越糟，然而正是中等程度的不确定性创造了其他框架所依赖的期权价值与创业机会。'),
      ],
      empirical=[
        P('Archival dynamism measures capture past volatility and are used to proxy expectations about the future, which are not the same quantity and can diverge sharply at exactly the moments that matter.',
          '档案式动态性指标捕捉的是过去的波动，却被用来代理对未来的预期；二者并非同一个量，且恰恰在关键时刻可能大幅背离。'),
        P('Perceived uncertainty is usually collected in the same survey as the decision it is supposed to explain, so the respondent may be rationalizing the decision rather than reporting the antecedent.',
          '感知不确定性通常与它本应解释的决策在同一份问卷中收集，受访者可能是在为决策作事后合理化，而非报告前因。'),
      ],
      temporal=[
        P('The archival proxies were designed for industries with stable boundaries and comparable sales series. Where firms compete across redefined category lines, a volatility measure computed within an industry code may be measuring the wrong environment entirely.',
          '档案代理是为边界稳定、销售序列可比的产业设计的。当企业跨越被重新定义的类别边界竞争时，按行业代码计算的波动率可能测的完全是另一个环境。'),
        P('The framework assumes information is scarce, so uncertainty falls as information is acquired. In settings with abundant, contradictory, and rapidly updated information, uncertainty can rise with information volume, which the original formulation does not anticipate.',
          '框架假定信息稀缺，因而获取信息会降低不确定性。在信息充裕、彼此矛盾且快速更新的情境中，不确定性可能随信息量上升——这是原始表述未曾预料的。'),
      ],
      today=[
        P('State the level and the type before choosing a measure. A study about managerial response needs a perceptual measure; a study about industry conditions needs an archival one, and neither substitutes for the other.',
          '在选择测量前先说明层面与类型。研究管理者反应需要感知测量，研究产业条件需要档案测量，二者不可互替。'),
        P('If the argument concerns ambiguity rather than uncertainty, say so and measure it separately. Framing problems do not respond to more information the way probability problems do.',
          '若论证关乎模糊性而非不确定性，应明确说明并单独测量。框定问题不像概率问题那样能靠更多信息解决。'),
      ]),

    # ------------------------------------------------------------------ status
    D('status',
      era='Sociological roots in the early 20th century; formalized for organizational and market research from the 1990s.',
      era_zh='社会学根源可追溯至 20 世纪初，1990 年代起在组织与市场研究中被形式化。',
      situation=[
        P('Markets were assumed to reward quality. Repeated observation showed that actors of similar quality received systematically different outcomes depending on their standing, and that the advantage persisted and compounded.',
          '市场被假定奖励质量。反复观察却显示：质量相近的行动者，会因所处地位不同而系统性地获得不同结果，且这种优势会持续并累积。'),
        P('Status supplied the mechanism. When quality is hard to observe, audiences use position in a prestige order as a signal, which allocates rewards to standing rather than to underlying quality.',
          '地位提供了机制。当质量难以观察时，受众会把声望秩序中的位置当作信号，于是回报被分配给地位而非底层质量。'),
      ],
      argument=[
        P('Status is a positional property conferred by an audience, not an attribute a person or firm owns. It exists only relative to others in a recognized order, which is what separates it from quality, reputation, and power.',
          '地位是由受众赋予的位置性属性，而非个人或企业自身拥有的特征。它只在被认可的秩序中相对于他人而存在——这正是它区别于质量、声誉与权力之处。'),
        P('The core prediction is decoupling: because status is sticky and quality fluctuates, high-status actors receive better outcomes than their current quality warrants, and low-status actors worse. This produces cumulative advantage.',
          '核心预测是脱耦：由于地位具有黏性而质量会波动，高地位者获得的结果好于其当前质量所应得，低地位者则相反。由此产生累积优势。'),
        P('Middle-status conformity follows from the same logic: those at the top and bottom of an order face less pressure to conform than those in the middle, whose position is both worth protecting and insecure.',
          '中等地位从众性由同一逻辑推出：秩序顶端与底端者面临的从众压力小于中间者，因为中间位置既值得保护又不稳固。'),
      ],
      development=[
        P('Market research applied it to certification, awards, and affiliation, showing that association with a high-status partner transfers standing independently of what the partnership produces.',
          '市场研究把它应用于认证、奖项与联结关系，表明与高地位伙伴的关联会独立于合作产出而转移地位。'),
      ],
      debates=[
        Debate('Is status separable from quality and reputation?', '地位能与质量、声誉分开吗？',
               [Pos('Distinctness position',
                    'Status is positional and conferred; reputation is a belief about past performance and quality is a property of the output. The three can move independently.',
                    '地位是位置性的、被赋予的；声誉是对过往表现的信念；质量是产出的属性。三者可以各自独立变动。'),
                Pos('Confounding critique',
                    'In practice status is measured with indicators that also track quality and reputation, so the reported status effect may be a quality effect measured badly.',
                    '实践中地位所用的指标同时追踪质量与声誉，因此报告的地位效应可能只是被测得很差的质量效应。')],
               'Open. The strongest designs hold quality constant by construction rather than controlling for it.',
               '未决。最有力的设计是通过构造使质量恒定，而非把它作为控制变量。'),
      ],
      theoretical=[
        P('Status is defined relative to an audience and an order, but is often treated as a single global standing, which loses the possibility of being high status in one field and low in another.',
          '地位是相对于某个受众与秩序定义的，却常被当作单一的全局位次，从而丢失了"在一个场域高地位、在另一个场域低地位"的可能。'),
        P('The framework explains persistence well and origin poorly. How an actor came to occupy a position is usually treated as historical accident.',
          '该框架对"地位为何延续"解释得好，对"地位如何形成"解释得差。行动者如何取得某一位置，通常被当作历史偶然处理。'),
      ],
      empirical=[
        P('Status is commonly proxied by network centrality, rankings, or affiliation counts, each of which is also a plausible cause of the outcome through non-status channels such as information access.',
          '地位常被网络中心度、排名或联结数量代理，而每一项都可能通过非地位渠道（如信息获取）合理地导致结果。'),
        P('Because status and outcomes reinforce each other, cross-sectional estimates are contaminated by reverse causality unless the design breaks the loop.',
          '由于地位与结果相互强化，除非设计能打断该循环，横截面估计会被反向因果污染。'),
      ],
      temporal=[
        P('The construct assumes a stable, widely recognized prestige order that most of the relevant audience shares. Platform ratings, algorithmic ranking, and fragmented audiences produce multiple simultaneous orders, and a single status score no longer has one referent.',
          '该构念假定存在稳定、被广泛承认、且多数相关受众共享的声望秩序。平台评分、算法排序与碎片化受众制造出多个并行的秩序，单一地位分数不再有唯一指称。'),
        P('It was formalized when status signals were scarce and slow to change — a prize, an affiliation, a ranking published annually. Continuously updated public metrics make standing volatile in a way that undercuts the stickiness the decoupling prediction depends on.',
          '它形式化于地位信号稀缺且变化缓慢之时——一个奖项、一段联结、一份年度排名。持续更新的公开指标使地位变得易变，从而削弱了脱耦预测所依赖的黏性。'),
      ],
      today=[
        P('Name the audience and the order. A status claim without them is not testable, because there is no standard against which position is defined.',
          '应指明受众与秩序。缺少二者的地位主张不可检验，因为没有可据以定义位置的标准。'),
        P('Design so that quality is held constant rather than controlled for. The whole contribution of the construct is what happens when quality is equal and standing is not.',
          '设计上应使质量恒定，而非把它作为控制变量。该构念的全部贡献，正在于"质量相同而地位不同"时会发生什么。'),
      ]),

    # ------------------------------------------- organizational identification
    D('organizational-identification',
      era='Brought into organizational research in 1989 from social identity theory; instrumented and heavily applied from the 1990s.',
      era_zh='1989 年自社会认同理论引入组织研究，1990 年代起形成量表并被大量应用。',
      situation=[
        P('Commitment explained why people stayed but not why they described the organization as we, defended it against outsiders, or took its setbacks personally.',
          '承诺能解释人们为何留下，却无法解释他们为何用"我们"称呼组织、对外维护它，或把它的挫折视为自己的挫折。'),
        P('Social identity theory already had the mechanism — self-concept partly derived from group membership — and the contribution was to apply it to the organization as the group.',
          '社会认同理论已有现成机制——自我概念部分源自群体成员身份——其贡献在于把组织作为该群体加以应用。'),
      ],
      argument=[
        P('Identification is the perceived overlap between self-concept and organizational identity. It is cognitive rather than affective: it concerns who I am, not how much I like it here, which is what separates it from commitment and satisfaction.',
          '认同是自我概念与组织身份之间的感知重叠。它是认知性而非情感性的：关乎"我是谁"，而非"我在这里有多愉快"——这正是它区别于承诺与满意度之处。'),
        P('The prediction is that identified members act on the organization behalf without incentive, because the organization interest is partly their own, and that they respond to threats to organizational identity as threats to self.',
          '预测是：认同的成员会在没有激励的情况下为组织行事，因为组织利益部分即是自身利益；他们也会把对组织身份的威胁当作对自我的威胁来回应。'),
      ],
      development=[
        P('Disidentification and ambivalent identification were added to handle members who define themselves against the organization or hold both orientations at once, which a single continuous scale cannot represent.',
          '为处理"以对抗组织来定义自我"或"同时持有两种取向"的成员，学界补入了去认同与矛盾认同——这是单一连续量表无法表达的。'),
      ],
      debates=[
        Debate('Is identification distinct from affective commitment?', '认同与情感承诺可区分吗？',
               [Pos('Distinctness position',
                    'Identification is self-definitional and commitment is attitudinal; a member can identify strongly while being ready to leave for a better offer.',
                    '认同是自我定义性的，承诺是态度性的；一名成员可以高度认同，同时准备为更好的机会离开。'),
                Pos('Redundancy critique',
                    'The two scales correlate at levels that make discriminant validity difficult to demonstrate, and applied studies rarely establish it.',
                    '两个量表的相关高到难以证明区分效度，而应用研究很少去证明它。')],
               'Partly settled in favour of distinctness at the conceptual level; the measurement problem remains.',
               '在概念层面基本判定为可区分；测量层面的问题仍然存在。'),
      ],
      theoretical=[
        P('Identification is treated as unambiguously positive, though strong identification also predicts defence of organizational wrongdoing and resistance to necessary change.',
          '认同被当作明确的正面变量，然而强认同同样预测对组织不当行为的辩护，以及对必要变革的抵制。'),
        P('The target is assumed to be the organization, but members simultaneously identify with team, profession, and employer, and these can conflict.',
          '认同对象被假定为组织，但成员同时认同团队、职业与雇主，而三者可能冲突。'),
      ],
      empirical=[
        P('Nearly all evidence is same-source self-report, and the outcomes most often studied — citizenship behaviour, intention to stay — are also self-rated.',
          '几乎全部证据都是同源自评，而最常研究的结果——公民行为、留任意向——同样是自评的。'),
        P('The standard scale asks about overlap in general terms, so a respondent who identifies with their team rather than the organization can score high without the construct being present.',
          '标准量表以笼统措辞询问重叠感，因此认同团队而非组织的受访者也可能得高分，而构念其实并不成立。'),
      ],
      temporal=[
        P('The construct assumes a single, visible, and reasonably stable organization to identify with. Remote work, contractor arrangements, and multi-employer careers weaken the shared symbols and daily co-presence through which organizational identity was assumed to be transmitted.',
          '该构念假定存在单一、可见且相对稳定的组织可供认同。远程工作、外包安排与多雇主职业削弱了共享符号与日常共同在场——而组织身份原本被假定正是经由它们传递的。'),
        P('It was formulated when the employer was the salient work group. Where professional communities and platform networks are more visible to a worker than their employer, the construct may be measuring the wrong target.',
          '它成形于"雇主即是显著工作群体"之时。当职业社群与平台网络对劳动者而言比雇主更可见时，该构念可能测的是错误的对象。'),
      ],
      today=[
        P('Specify and measure the target. Asking about the organization while the respondent is thinking about their team produces a number that does not test the theory.',
          '应明确并测量认同对象。在受访者心里想的是团队时去问组织，得到的数字并不检验该理论。'),
        P('If the study concerns dysfunctional loyalty or resistance to change, identification is the right construct and its positive framing should not be carried over uncritically.',
          '若研究关乎失能的忠诚或对变革的抵制，认同正是恰当的构念，但不应不加批判地沿用其正面框定。'),
      ]),

    # ------------------------------------------------------- capital structure
    D('capital-structure',
      era='Irrelevance benchmark established in 1958; the trade-off and pecking-order accounts developed through the 1970s and 1980s.',
      era_zh='1958 年确立无关性基准，权衡理论与优序融资理论于 1970—1980 年代发展成形。',
      situation=[
        P('Before 1958 there was no benchmark: financing mix was discussed as a practical matter without a theory saying what it should depend on.',
          '1958 年之前没有基准：融资结构只被当作实务问题讨论，没有理论说明它应取决于什么。'),
        P('The irrelevance result supplied one by proving that under frictionless markets the mix cannot affect firm value. Its purpose was not to describe reality but to identify which frictions must be doing the work.',
          '无关性结论提供了基准：它证明在无摩擦市场中融资结构无法影响企业价值。其用意不是描述现实，而是识别究竟哪些摩擦在起作用。'),
      ],
      argument=[
        P('Each subsequent theory names a friction. The trade-off account balances the tax deductibility of interest against expected bankruptcy costs, implying an optimal ratio firms move toward.',
          '此后每一个理论都指认一种摩擦。权衡理论在利息税盾与预期破产成本之间取舍，推出企业会朝之调整的最优比率。'),
        P('The pecking-order account starts from information asymmetry instead: managers know more than investors, issuing equity signals overvaluation, so firms prefer internal funds, then debt, then equity as a last resort. It predicts no target ratio at all.',
          '优序融资理论则从信息不对称出发：管理者比投资者知道更多，增发股权释放"高估"信号，因此企业优先使用内部资金，其次债务，股权为最后手段。它根本不预测目标比率。'),
        P('The two make incompatible predictions about whether firms have a target and revert to it, which is why the literature is organized as a contest between them rather than an accumulation.',
          '二者对"企业是否存在目标比率并向其回归"作出互不相容的预测，这正是该文献呈现为对立竞争而非知识累积的原因。'),
      ],
      development=[
        P('Market timing added a third account in which firms issue whichever security is currently favourably priced, so the observed structure is the accumulated residue of past timing decisions rather than any optimum.',
          '市场择时理论提供了第三种解释：企业发行当前定价有利的证券，因此观察到的结构是过往择时决策的累积残留，而非任何最优解。'),
      ],
      debates=[
        Debate('Do firms have a target leverage ratio?', '企业存在目标杠杆率吗？',
               [Pos('Trade-off position',
                    'Leverage reverts toward an industry- and firm-specific target after shocks, which is evidence of an optimum being pursued.',
                    '杠杆在冲击后向产业与企业特定的目标回归，这是"存在最优并被追求"的证据。'),
                Pos('Pecking-order and timing position',
                    'Apparent reversion is mechanical mean reversion in a bounded ratio and is also produced by models with no target at all.',
                    '表面上的回归是有界比率的机械均值回复，没有目标的模型同样能产生这一现象。')],
               'Unresolved after decades. Tests that distinguish the accounts require predictions about issuance decisions, not just about the level of leverage.',
               '数十年未决。能区分各理论的检验需要针对"发行决策"作出预测，而非仅针对杠杆水平。'),
      ],
      theoretical=[
        P('The theories were built for firms with tangible assets that can serve as collateral and a bankruptcy process that resolves claims predictably; both assumptions bind less for intangible-intensive firms.',
          '这些理论建立在"有可作抵押的有形资产、且破产程序能可预测地清偿债权"之上；对无形资产密集型企业而言，两个假定的约束力都弱得多。'),
        P('Leverage is treated as a choice, but for many firms it is a constraint set by what lenders will supply.',
          '杠杆被当作一种选择，但对许多企业而言它是由"贷方愿意提供多少"所设定的约束。'),
      ],
      empirical=[
        P('Book and market leverage frequently disagree, and results can reverse depending on which is used; papers should report both and explain divergence.',
          '账面杠杆与市值杠杆经常不一致，结论可能随所选口径反转；论文应同时报告并解释背离。'),
        P('Profitability is negatively related to leverage in almost every sample, which the pecking order predicts and the trade-off account does not, yet the finding has not settled the debate because both sides can accommodate it with auxiliary assumptions.',
          '几乎每个样本中盈利能力都与杠杆负相关——这是优序融资的预测而非权衡理论的预测；但该发现并未终结争论，因为双方都能以辅助假定加以容纳。'),
      ],
      temporal=[
        P('The tax-shield mechanism depends on a specific corporate tax treatment of interest. Tax reforms that cap interest deductibility remove part of the benefit the trade-off account rests on, so results estimated under older regimes do not transfer automatically.',
          '税盾机制依赖利息在企业所得税上的特定处理。限制利息抵扣的税制改革削去了权衡理论所依赖的部分收益，因此在旧税制下估计的结果不能自动迁移。'),
        P('The frameworks assume debt and equity are the relevant claims. Venture financing structures, convertible instruments, and firms that fund growth from platform cash flows without external capital sit outside the binary the theories were built around.',
          '这些框架假定债务与股权是相关的求偿权。风险融资结构、可转换工具，以及依靠平台现金流而不动用外部资本的企业，都落在理论所围绕的二元之外。'),
      ],
      today=[
        P('State which friction the study is about and design the test around issuance behaviour, since the level of leverage alone cannot separate the competing accounts.',
          '应说明研究关注哪一种摩擦，并围绕发行行为设计检验；仅凭杠杆水平无法区分相互竞争的解释。'),
        P('For intangible-intensive and platform firms, treat the collateral and bankruptcy assumptions as boundary conditions to be argued rather than as background.',
          '对无形资产密集型与平台企业，应把抵押与破产假定当作需要论证的边界条件，而非默认背景。'),
      ]),

    # --------------------------------------------------------- interdependence
    D('interdependence',
      era='Formalized in social psychology in 1959; adapted to task design and organization theory from the 1960s and 1970s.',
      era_zh='1959 年在社会心理学中形式化，1960—1970 年代被引入任务设计与组织理论。',
      situation=[
        P('Group research needed a way to say why the same people produce different outcomes in different task structures. Individual attributes could not explain it; the structure of who depends on whom had to enter the model.',
          '群体研究需要说明：为何同一批人在不同任务结构下产生不同结果。个体特征解释不了，"谁依赖谁"的结构必须进入模型。'),
        P('Organization theory needed the same thing at a larger scale, to explain why some units require constant coordination and others can be left alone.',
          '组织理论在更大尺度上有同样需求：解释为何某些单元需要持续协调，而另一些可以放手不管。'),
      ],
      argument=[
        P('Interdependence is a property of the structure, not of the people in it. It is the extent to which one actor outcomes, choices, or resources depend on another, and it can be specified before any behaviour is observed.',
          '相互依赖是结构的属性，而非其中人的属性。它指一方的结果、选择或资源在多大程度上依赖于另一方，且可以在观察到任何行为之前就被设定。'),
        P('The organizational typology orders it by coordination cost: pooled, where units share resources but not work; sequential, where output flows one way; and reciprocal, where units feed back into each other and require mutual adjustment.',
          '组织层面的类型学按协调成本排序：共享型，单元共用资源但不共用工作；顺序型，产出单向流动；互惠型，单元相互反馈、需要相互调整。'),
        P('The prediction is that coordination mechanism should match interdependence type. Standardization suffices for pooled, planning for sequential, and mutual adjustment is required for reciprocal, which is why the last is the expensive case.',
          '预测是：协调机制应与相互依赖类型匹配。共享型用标准化即可，顺序型用计划，互惠型则必须相互调整——这正是最后一种代价高昂的原因。'),
      ],
      development=[
        P('Task interdependence and outcome interdependence were separated: sharing work is not the same as sharing rewards, and the two have different effects on cooperation and on conflict.',
          '任务相互依赖与结果相互依赖被区分开：共担工作不同于共享回报，二者对合作与冲突的影响不同。'),
      ],
      debates=[
        Debate('Is interdependence objective or perceived?', '相互依赖是客观的还是感知的？',
               [Pos('Structural position',
                    'It is a property of the workflow and can be coded from task design independently of anyone report.',
                    '它是工作流的属性，可以脱离任何人的报告、直接从任务设计中编码。'),
                Pos('Perceptual position',
                    'Coordination behaviour responds to what members believe about dependence, and structural coding routinely disagrees with member reports.',
                    '协调行为回应的是成员对依赖关系的信念，而结构化编码常与成员报告不一致。')],
               'Open. Studies that use both and report the disagreement are more informative than those that pick one silently.',
               '未决。同时使用两者并报告其分歧的研究，比默默择一的研究更有信息量。'),
      ],
      theoretical=[
        P('Reciprocal interdependence is treated as the extreme of a single ordered scale, but reciprocity is a different structure rather than simply more of the same thing.',
          '互惠型相互依赖被当作单一有序量表的极端，但互惠是一种不同的结构，而非同一事物的"更多"。'),
        P('Interdependence is defined between actors, yet most studies measure it as an individual perception and analyse it at the individual level, which discards the structure that defines it.',
          '相互依赖定义在行动者之间，多数研究却把它作为个体感知来测量并在个体层面分析，从而丢弃了定义它的那个结构。'),
      ],
      empirical=[
        P('Self-reported interdependence is measured alongside the coordination and performance outcomes it predicts, so the direction of the relationship is not established by the design.',
          '自评的相互依赖与它所预测的协调和绩效结果一同测量，因此设计本身并未确立关系方向。'),
        P('Team-level constructs are frequently aggregated from individual responses without reporting agreement statistics, which is required before treating the aggregate as a shared property.',
          '团队层面构念常由个体作答聚合而成，却不报告一致性统计量——而在把聚合值当作共享属性之前，这是必需的。'),
      ],
      temporal=[
        P('The typology was built for workflows a manager could see and design. Where task allocation is performed continuously by a system, interdependence is set by routing logic that no participant observes, and structural coding from a documented process may not describe the dependence that actually operates.',
          '该类型学是为管理者可见、可设计的工作流构建的。当任务分配由系统持续执行时，相互依赖由无人可见的派单逻辑设定，依据书面流程所做的结构化编码，可能并不描述真正在起作用的依赖关系。'),
        P('Mutual adjustment was theorized as face-to-face negotiation among people who could find each other. Distributed and asynchronous work raises its cost substantially, so the coordination mechanism the theory prescribes for reciprocal interdependence is harder to supply than when the prescription was written.',
          '相互调整被设想为彼此能找到对方的人之间面对面的协商。分布式与异步工作大幅抬高其成本，因此理论为互惠型依赖开出的协调机制，如今比该处方写就之时更难提供。'),
      ],
      today=[
        P('Code the structure from the workflow where possible and treat perception as a separate variable rather than a substitute. Disagreement between them is often the interesting finding.',
          '尽可能从工作流编码结构，并把感知作为独立变量而非替代品。二者的分歧往往才是有意思的发现。'),
        P('For algorithmically coordinated work, describe how the system allocates tasks before claiming an interdependence type; the documented process and the operating one frequently differ.',
          '研究算法协调的工作时，应先描述系统如何分配任务，再断言其相互依赖类型；书面流程与实际运行常常不同。'),
      ]),
])
