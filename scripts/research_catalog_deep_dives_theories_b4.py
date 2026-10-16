# -*- coding: utf-8 -*-
"""Deep dives for catalog theories, batch 4: information systems.

The IS channel had only TAM and UTAUT written up. These six complete the core:
diffusion, media richness, affordances, privacy calculus, the success model, and
task-technology fit.

Schema helpers live in ``research_catalog_deep_dives``.
"""

from research_catalog_deep_dives import D, Debate, P, Pos

THEORY_DIVES_B4 = dict([

    # ------------------------------------------------ diffusion of innovations
    D('diffusion-of-innovations',
      era='First edition 1962, revised across five editions to 2003; the most widely applied adoption framework outside economics.',
      era_zh='1962 年初版，历经五版修订至 2003 年，是经济学之外应用最广的采纳框架。',
      situation=[
        P('Adoption studies in agriculture, medicine, and education had each produced their own findings about why some innovations spread and others did not, with no shared vocabulary across fields.',
          '农业、医学与教育领域各自积累了关于"为何某些创新扩散而另一些不然"的发现，却没有跨领域的共同词汇。'),
        P('The synthesis proposed that diffusion has a common structure regardless of what is diffusing: a social system, communication channels, time, and an innovation with perceivable attributes.',
          '该综合主张：无论扩散的是什么，扩散都具有共同结构——社会系统、沟通渠道、时间，以及具有可感知属性的创新。'),
      ],
      argument=[
        P('Adoption depends on five perceived attributes: relative advantage over what it replaces, compatibility with existing values and practice, complexity, trialability, and observability of results.',
          '采纳取决于五项被感知的属性：相对于被替代物的相对优势、与既有价值和实践的兼容性、复杂性、可试用性，以及结果的可观察性。'),
        P('Diffusion follows an S-curve because adopters differ in threshold: innovators and early adopters move on the attributes, while the later majority moves largely because others already have.',
          '扩散呈 S 形曲线，因为采纳者的阈值不同：创新者与早期采纳者依据属性行动，而后期多数则主要因为他人已经采纳。'),
        P('Opinion leaders and change agents are the mechanism connecting the two: the curve steepens when adoption crosses from people who evaluate the innovation to people who observe their peers.',
          '意见领袖与变革推动者是连接二者的机制：当采纳从"评估创新的人"跨越到"观察同侪的人"时，曲线陡然上升。'),
      ],
      development=[
        P('Organizational adoption research adapted it from individuals to firms, where the adoption decision is collective and the implementation stage matters as much as the decision.',
          '组织采纳研究把它从个体调整到企业：那里的采纳决策是集体的，实施阶段与决策同等重要。'),
      ],
      debates=[
        Debate('Are adopter categories explanatory or descriptive?', '采纳者类别是解释性的还是描述性的？',
               [Pos('Categorical position',
                    'Innovators, early adopters, and laggards differ systematically in resources, networks, and risk tolerance, and those differences predict timing.',
                    '创新者、早期采纳者与落后者在资源、网络与风险承受上存在系统差异，这些差异预测采纳时点。'),
                Pos('Artefact critique',
                    'The categories are defined by position on the adoption curve, so saying early adopters adopt early is definitional rather than explanatory.',
                    '这些类别是按在采纳曲线上的位置定义的，因此"早期采纳者较早采纳"是定义而非解释。')],
               'The critique is widely accepted; the categories survive as a descriptive vocabulary rather than a causal account.',
               '该批评已被广泛接受；这些类别作为描述性词汇而非因果解释而存续。'),
      ],
      theoretical=[
        P('The framework carries a pro-innovation bias: it explains adoption far better than rejection, discontinuance, or the possibility that not adopting was correct.',
          '框架带有亲创新偏向：它对采纳的解释远好于对拒绝、中止，或"不采纳才是对的"这一可能性的解释。'),
        P('The S-curve is an aggregate pattern and says nothing about any individual decision, though it is routinely used as if it did.',
          'S 形曲线是聚合模式，对任何个体决策都无所言说，却常被当作有所言说来使用。'),
      ],
      empirical=[
        P('Diffusion curves are fitted to cumulative adoption data, and almost any spreading process produces an S shape, so curve fit is weak evidence for the mechanism.',
          '扩散曲线拟合的是累计采纳数据，而几乎任何扩散过程都会产生 S 形，因此曲线拟合对机制而言是弱证据。'),
        P('Perceived attributes are usually measured after adoption, when adopters rationalize their choice, which inflates the attribute-adoption relationship.',
          '被感知的属性通常在采纳之后测量，此时采纳者会为自己的选择作合理化，从而抬高属性与采纳之间的关系。'),
      ],
      temporal=[
        P('The framework assumes adoption is a decision an individual or firm makes and can decline. Where a capability arrives as a mandatory update to software already in use, there is no adoption decision to model and the attribute logic has nothing to act on.',
          '框架假定采纳是个体或企业可以拒绝的决策。当某项能力以"已在使用软件的强制更新"形式到来时，没有可建模的采纳决策，属性逻辑也就无从作用。'),
        P('It was built when diffusion ran through interpersonal contact and observation of peers. Where spread is driven by platform defaults, recommendation, and bundling, the communication channel in the model is an intermediary rather than a peer, and opinion leadership is not the operative mechanism.',
          '它建立于扩散经由人际接触与观察同侪进行的时期。当扩散由平台默认、推荐与捆绑驱动时，模型中的沟通渠道是中介而非同侪，意见领袖也不再是起作用的机制。'),
      ],
      today=[
        P('Use it where adoption is genuinely voluntary and sequential. Where it is mandated or defaulted, the framework describes the pattern without explaining it.',
          '应在采纳确实自愿且有先后顺序时使用它。当采纳是强制或默认的，框架只描述模式而不解释它。'),
        P('Measure the perceived attributes before adoption if the causal claim is about them, and report non-adopters, who are missing from most diffusion samples.',
          '若因果主张关乎被感知属性，应在采纳之前测量；并报告未采纳者——他们在多数扩散样本中是缺失的。'),
      ]),

    # ------------------------------------------------------- media richness
    D('media-richness-theory',
      era='Published 1986; challenged empirically through the 1990s and largely overtaken by adaptation-based accounts.',
      era_zh='1986 年发表，1990 年代在经验上受到挑战，此后大体被基于适应的解释取代。',
      situation=[
        P('Organizations were choosing among a growing set of communication media and had no principled basis for the choice. The practical question was which medium suits which task.',
          '组织面对日益增多的沟通媒介，却没有作出选择的原则依据。现实问题是：哪种媒介适合哪类任务。'),
        P('The theory supplied one by treating media as differing in a measurable capacity and tasks as differing in what they require, so the answer is a matching problem.',
          '该理论提供了依据：把媒介视为在某种可测能力上有差异、任务视为在需求上有差异，从而把答案化为一个匹配问题。'),
      ],
      argument=[
        P('Richness is a medium capacity to carry cues, provide immediate feedback, use natural language, and convey personal focus. Face-to-face is richest, formal written documents leanest.',
          '丰富性指媒介传递线索、提供即时反馈、使用自然语言与表达个人化关注的能力。面对面最丰富，正式书面文件最贫瘠。'),
        P('Tasks differ in equivocality — whether the problem is ambiguity of meaning or merely absence of data. Equivocal tasks need rich media to negotiate meaning; unequivocal ones need only enough capacity to transmit facts.',
          '任务在模糊性上不同——问题究竟是意义含混，还是仅仅缺少数据。模糊任务需要丰富媒介来协商意义；不模糊的任务只需足够传递事实的容量。'),
        P('Performance follows the match. Using a lean medium for an equivocal task leaves meaning unresolved; using a rich medium for a simple one wastes attention.',
          '绩效取决于匹配。用贫瘠媒介处理模糊任务会使意义悬而未决；用丰富媒介处理简单任务则浪费注意力。'),
      ],
      development=[
        P('Channel expansion and adaptive structuration accounts argued that richness is not fixed: experience with a medium, with the topic, and with the other party changes how much a given channel can carry.',
          '渠道扩展与适应性结构化的解释主张丰富性并非固定：对媒介、话题与对方的经验，会改变同一渠道所能承载的信息量。'),
      ],
      debates=[
        Debate('Is richness a property of the medium?', '丰富性是媒介的属性吗？',
               [Pos('Original position',
                    'Richness is an objective capacity that can be ranked, which is what makes the matching prediction testable.',
                    '丰富性是可以排序的客观能力，这正是匹配预测得以检验的前提。'),
                Pos('Social construction position',
                    'Experienced users convey nuance through lean channels routinely, so richness is produced in use rather than carried by the medium.',
                    '有经验的用户经常通过贫瘠渠道传达细微差别，因此丰富性产生于使用之中，而非由媒介承载。')],
               'Settled substantially in favour of the social account; the original ranking survives as a rough heuristic.',
               '在很大程度上判定为社会建构一方；原初排序作为粗略启发法而存续。'),
      ],
      theoretical=[
        P('The theory is normative about what managers should choose but is frequently tested on what they do choose, which conflates prescription with description.',
          '该理论对"管理者应选什么"是规范性的，检验时却常针对"他们实际选了什么"，从而混淆了处方与描述。'),
        P('Richness is treated as unidimensional, though cue variety and feedback immediacy can vary independently and matter for different tasks.',
          '丰富性被当作一维，然而线索多样性与反馈即时性可以独立变化，且对不同任务的重要性不同。'),
      ],
      empirical=[
        P('Support is strongest in laboratory studies with inexperienced users and weakest in field settings, which is the pattern the adaptation critique predicts.',
          '支持在"被试缺乏经验"的实验室研究中最强、在现场情境中最弱——而这正是适应性批评所预测的模式。'),
        P('Media choice is confounded with availability, cost, and norms, so an observed choice is weak evidence about perceived richness.',
          '媒介选择与可得性、成本与规范相混淆，因此观察到的选择对"感知丰富性"而言是弱证据。'),
      ],
      temporal=[
        P('The ranking was constructed when media were few, discrete, and had stable properties. Contemporary channels are multi-modal and configurable — a message thread can carry text, voice, video, and persistent history at once — so a single richness position on the scale does not describe them.',
          '该排序构建于媒介数量少、离散、属性稳定之时。当代渠道是多模态且可配置的——一个消息线程可以同时承载文本、语音、视频与持久历史——因此单一的丰富性位次无法描述它们。'),
        P('The theory has no account of persistence and searchability, which are now central: a written channel that is leaner in the original ranking may be preferred precisely because it leaves a record, a consideration the framework does not contain.',
          '该理论没有关于持久性与可检索性的解释，而这两点如今至关重要：在原排序中更"贫瘠"的书面渠道，可能恰恰因为留下记录而被偏好——这一考量不在框架之内。'),
      ],
      today=[
        P('Treat the ranking as a heuristic, not a prediction, and measure experience with the medium as a moderator if the matching hypothesis is being tested.',
          '应把该排序视为启发法而非预测；若要检验匹配假设，应把对媒介的经验作为调节变量加以测量。'),
        P('For hybrid and asynchronous work, persistence and audience are usually more consequential than richness, and a design should say why richness is the right dimension.',
          '在混合与异步工作中，持久性与受众通常比丰富性更有后果；研究设计应说明为何丰富性才是恰当的维度。'),
      ]),

    # ---------------------------------------------------------- affordance theory
    D('affordance-theory',
      era='Imported from ecological psychology; established in information systems research from around 2008 to 2013.',
      era_zh='源自生态心理学，约 2008—2013 年在信息系统研究中确立。',
      situation=[
        P('IS research was caught between technological determinism, in which the artefact produces outcomes, and social constructivism, in which only interpretation matters and the artefact drops out.',
          'IS 研究夹在两种立场之间：技术决定论认为人工物产生结果，社会建构论则认为只有解读重要、人工物本身消失。'),
        P('Neither could explain why the same system produces different outcomes in different organizations while still constraining what is possible in all of them.',
          '两者都无法解释：为何同一系统在不同组织中产生不同结果，却同时在所有组织中都限定了可能性的范围。'),
      ],
      argument=[
        P('An affordance is an action possibility that exists in the relation between a technology and a goal-directed actor. It is neither in the artefact nor in the person, which is precisely what lets the theory hold both without collapsing into either.',
          '可供性是存在于技术与有目标行动者之间关系中的行动可能性。它既不在人工物中也不在人身上——这正是该理论能同时容纳两者而不倒向任何一方的原因。'),
        P('Affordances must be perceived and then actualized. A system can afford something nobody notices, or something noticed but blocked by organizational conditions, so the existence of an affordance does not predict the outcome.',
          '可供性必须先被感知、再被实现。系统可以提供无人察觉的可能，也可以提供被察觉却因组织条件而受阻的可能；因此可供性的存在并不预测结果。'),
        P('Constraints are the symmetric concept: the same relation that makes some actions possible makes others harder, and a complete account names both.',
          '约束是对称概念：使某些行动成为可能的同一关系，也使另一些行动变得更难；完整的解释应同时指明两者。'),
      ],
      development=[
        P('Affordance actualization and affordance-effect chains were introduced to connect the possibility to the organizational outcome, which the original relational definition did not do.',
          '可供性实现与"可供性—效应链"被引入，用以把"可能性"连到组织结果——而原初的关系式定义并未做到这一点。'),
      ],
      debates=[
        Debate('Is the concept explanatory or a relabelling?', '这个概念是解释还是换名？',
               [Pos('Explanatory position',
                    'It resolves the determinism-constructivism impasse by locating the effect in a relation, which neither prior position could do.',
                    '它把效应定位于一种关系，从而化解了决定论与建构论的僵局——这是此前任何一方都做不到的。'),
                Pos('Relabelling critique',
                    'In practice affordances are identified after observing what people did, which describes the outcome in new vocabulary rather than explaining it.',
                    '实践中可供性是在观察到人们做了什么之后才被识别的，这只是用新词汇描述结果，而非解释它。')],
               'Open, and it hinges on whether a study identifies affordances independently of the outcome, which few do.',
               '未决，关键在于研究是否独立于结果来识别可供性——而很少有研究做到。'),
      ],
      theoretical=[
        P('Because affordances are relational, they cannot be enumerated for a technology in general, which limits cumulative theory building across studies of the same system.',
          '由于可供性是关系性的，无法对某项技术作一般性枚举，这限制了针对同一系统的跨研究理论累积。'),
        P('The concept is applied at inconsistent levels — a feature, a system, a class of technology — and results at one level do not transfer to another.',
          '该概念被应用于不一致的层次——某项功能、某个系统、某类技术——而一个层次上的结果无法迁移到另一层次。'),
      ],
      empirical=[
        P('Identification is usually retrospective, from observed use, which risks circularity: the affordance is inferred from the action it is supposed to explain.',
          '识别通常是从已观察到的使用回溯进行的，存在循环风险：可供性是从它本应解释的行动中推断出来的。'),
        P('Actualization depends on organizational conditions that are frequently not measured, so a non-actualized affordance and an absent one look the same in the data.',
          '实现取决于常常未被测量的组织条件，因此"未被实现的可供性"与"不存在的可供性"在数据中看起来相同。'),
      ],
      temporal=[
        P('The concept assumes the artefact has stable properties that stand in relation to the actor. Systems that adapt to the individual user offer different possibilities to different people and change over time, so the affordance is not a stable relation and comparison across users is not comparison of the same thing.',
          '该概念假定人工物具有与行动者相对的稳定属性。会随个体用户自适应的系统对不同人提供不同可能、并随时间变化，因此可供性不是稳定关系，跨用户比较也不是在比较同一事物。'),
        P('It was developed for technologies whose action possibilities a user could discover by exploration. Where capability is discovered through natural-language interaction, what a system affords depends on what the user thought to ask, which makes perception and affordance harder to separate than the framework assumes.',
          '它针对的是用户可通过探索发现其行动可能的技术。当能力经由自然语言交互被发现时，系统提供什么取决于用户想到问什么——这使感知与可供性比框架所设想的更难分离。'),
      ],
      today=[
        P('Identify the affordance from the technology and the actor goal before observing the outcome, or state that the identification is retrospective.',
          '应在观察结果之前，从技术与行动者目标出发识别可供性；否则应说明该识别是回溯性的。'),
        P('Report constraints alongside affordances. A study that only lists what became possible has described half of the relation.',
          '应在报告可供性的同时报告约束。只列出"什么变得可能"的研究，只描述了关系的一半。'),
      ]),

    # ------------------------------------------------------ privacy calculus
    D('privacy-calculus-theory',
      era='Formulated in 1999 and 2006; the paradox it was built to explain has proved durable.',
      era_zh='1999 与 2006 年成形，它所要解释的悖论至今顽固存在。',
      situation=[
        P('Survey research kept finding high privacy concern alongside extensive disclosure. Treating that as irrational left nothing to model, and treating concern as simply not predictive abandoned the construct.',
          '问卷研究不断发现高隐私关注与广泛披露并存。把它当作非理性则无从建模，把关注度当作不具预测力则等于放弃该构念。'),
        P('The calculus reframed it as a trade-off rather than an inconsistency: people disclose when the anticipated benefit outweighs the perceived risk, so high concern and disclosure can coexist coherently.',
          '计算框架把它重述为权衡而非不一致：当预期收益超过感知风险时人们就会披露，因此高关注与披露可以一致并存。'),
      ],
      argument=[
        P('Disclosure is modelled as a rational trade-off. Perceived risk lowers intention to disclose; anticipated benefit raises it; trust and perceived control shift the weighting by lowering the risk side.',
          '披露被建模为理性权衡：感知风险降低披露意向，预期收益提高它；信任与感知控制通过降低风险一侧来改变权重。'),
        P('The framework therefore predicts that raising perceived control increases disclosure, which is the counter-intuitive implication that has received the most support and the most concern.',
          '因此框架预测：提高感知控制会增加披露——这是它最反直觉、也最受支持同时最引人忧虑的推论。'),
      ],
      development=[
        P('Extensions added affect, habit, and social norms, on the evidence that routine disclosures are not deliberated at all, which weakens the calculus premise while improving prediction.',
          '扩展加入了情绪、习惯与社会规范，依据是日常披露根本未经深思——这在改善预测的同时削弱了计算式前提。'),
      ],
      debates=[
        Debate('Does perceived control protect or increase exposure?', '感知控制是保护还是增加暴露？',
               [Pos('Protective position',
                    'Control mechanisms let people disclose selectively and are the appropriate policy response to privacy concern.',
                    '控制机制让人们能够选择性披露，是应对隐私关注的恰当政策回应。'),
                Pos('Control paradox position',
                    'Perceived control lowers perceived risk more than it lowers actual risk, so giving people controls increases total disclosure and net exposure.',
                    '感知控制降低感知风险的幅度大于降低实际风险的幅度，因此提供控制反而增加总披露量与净暴露。')],
               'The control paradox has substantial support and is the most policy-relevant finding in this literature.',
               '控制悖论获得相当支持，是该文献中与政策最相关的发现。'),
      ],
      theoretical=[
        P('The calculus assumes deliberation and a real choice. Where the alternative to disclosure is not using a service with no substitute, modelling the outcome as a preference-revealing trade-off misdescribes it.',
          '计算框架假定深思与真实选择。当"不披露"意味着不能使用一项没有替代品的服务时，把结果建模为"揭示偏好的权衡"是对它的错误描述。'),
        P('Risk is treated as a perception the individual holds, but privacy harms are frequently collective and delayed, which an individual calculus cannot represent.',
          '风险被当作个体持有的感知，然而隐私伤害常常是集体的、延迟的，个体计算无法表达这一点。'),
      ],
      empirical=[
        P('Almost all tests use stated intention in hypothetical scenarios, and the gap between stated and actual disclosure is precisely the phenomenon under study.',
          '几乎所有检验都在假想情境中使用陈述意向，而"陈述与实际披露之间的落差"恰恰正是所研究的现象本身。'),
        P('Benefit and risk are measured with items that reference the same scenario as the disclosure decision, so the trade-off is partly built into the instrument.',
          '收益与风险的题项与披露决策指向同一情境，因此权衡在某种程度上已被内建于测量工具中。'),
      ],
      temporal=[
        P('The framework assumes a discrete disclosure event the person can evaluate. Where data are collected ambiently and inferred from behaviour, there is no decision point at which a calculus could be performed, and the mechanism has no occasion to operate.',
          '框架假定存在个体可以评估的离散披露事件。当数据以环境方式采集、并从行为中推断时，不存在可以进行计算的决策点，机制也就没有作用的时机。'),
        P('It was formulated when the benefit of disclosure was immediate and legible — a personalized service, a completed transaction. Where the benefit is a marginally better recommendation and the risk is an inference years later, the two sides of the calculus are not commensurable in the way the model requires.',
          '它成形于披露的收益即时且可辨识之时——个性化服务、完成的交易。当收益只是稍好的推荐、风险却是数年后的推断时，计算的两侧并不具备模型所要求的可通约性。'),
      ],
      today=[
        P('Observe actual disclosure where possible and report whether a genuine alternative existed. Without that the finding is about stated preference under a forced choice.',
          '应尽可能观察实际披露，并报告是否存在真实替代选项。缺少这一点，发现只是关于"被迫选择下的陈述偏好"。'),
        P('If studying control mechanisms, measure net exposure rather than satisfaction with the controls. The control paradox means the two can move in opposite directions.',
          '若研究控制机制，应测量净暴露而非对控制功能的满意度。控制悖论意味着二者可能朝相反方向变动。'),
      ]),

    # ---------------------------------------------------------- IS success model
    D('is-success-model',
      era='Proposed in 1992 and updated in 2003; the standard dependent-variable framework in IS evaluation research.',
      era_zh='1992 年提出，2003 年更新，是信息系统评估研究中标准的因变量框架。',
      situation=[
        P('IS research had accumulated studies using incompatible success measures — usage, satisfaction, profitability, perceived value — so findings could not be compared and the field had no agreed dependent variable.',
          'IS 研究积累了大量使用互不兼容成功指标的研究——使用量、满意度、盈利、感知价值——因此结果无法比较，该领域也没有公认的因变量。'),
        P('The contribution was taxonomic: organize the candidate measures into a structure with stated relationships rather than argue for one of them.',
          '其贡献是分类学意义上的：把候选指标组织为具有明确关系的结构，而不是主张其中某一个。'),
      ],
      argument=[
        P('Six interdependent dimensions: system quality, information quality, and service quality feed use and user satisfaction, which reciprocally influence each other and jointly produce net benefits.',
          '六个相互依赖的维度：系统质量、信息质量与服务质量影响使用与用户满意度，二者相互影响，并共同产生净收益。'),
        P('The structure is deliberately a process as well as a variance model: quality precedes use, use and satisfaction precede benefits, and benefits feed back into subsequent use.',
          '该结构被刻意设计为既是过程模型也是方差模型：质量先于使用，使用与满意先于收益，收益又反馈到后续使用。'),
        P('Net benefits is intentionally open, to be specified by the researcher for a stated stakeholder and level, which is the model main flexibility and its main weakness.',
          '"净收益"被有意留空，由研究者针对特定利益相关者与层次加以界定——这既是该模型最大的灵活性，也是其最大的弱点。'),
      ],
      development=[
        P('Service quality was added in the 2003 update as IS functions moved from delivering systems to delivering services, and the multiple original benefit categories were collapsed into net benefits.',
          '2003 年的更新加入服务质量，因为 IS 职能从交付系统转向交付服务；同时把原有的多个收益类别合并为净收益。'),
      ],
      debates=[
        Debate('Is use a measure of success?', '使用量是成功的指标吗？',
               [Pos('Inclusion position',
                    'Voluntary use reveals that the system delivers value, and it is observable where satisfaction is not.',
                    '自愿使用揭示系统确实提供价值，且在满意度不可观察时它可被观察。'),
                Pos('Exclusion position',
                    'Where use is mandatory it measures compliance, and more use can indicate inefficiency rather than benefit.',
                    '当使用是强制的，它测的是合规；而使用越多也可能意味着低效而非收益。')],
               'Settled that use is only interpretable when voluntary, though it continues to be reported in mandatory settings.',
               '已有定论：使用量只在自愿情形下可解读；但在强制情境中它仍被继续报告。'),
      ],
      theoretical=[
        P('Net benefits is a placeholder rather than a construct. Two studies can both claim to test the model while measuring incompatible outcomes for different stakeholders.',
          '净收益是占位符而非构念。两项研究可以都声称检验该模型，却为不同利益相关者测量互不兼容的结果。'),
        P('The reciprocal relationships between use and satisfaction cannot be identified from cross-sectional data, which is what most tests use.',
          '使用与满意之间的互惠关系无法从横截面数据中识别，而多数检验用的正是横截面数据。'),
      ],
      empirical=[
        P('Quality dimensions are measured perceptually by the same users who report satisfaction and benefit, so the model is often tested entirely within one respondent perception.',
          '质量维度由报告满意度与收益的同一批用户主观评定，因此该模型常常完全在同一受访者的感知内部被检验。'),
        P('The full model is rarely tested; most studies estimate a fragment and cite the whole framework, which makes the accumulated evidence hard to assess.',
          '完整模型很少被检验；多数研究只估计其中一个片段却引用整个框架，这使累积证据难以评估。'),
      ],
      temporal=[
        P('The model assumes a bounded system with identifiable users, a quality that can be assessed, and a benefit attributable to it. Where capability is delivered continuously through platforms and embedded services, the system whose success is being measured has no clear boundary.',
          '模型假定存在边界清晰的系统、可辨识的用户、可评估的质量，以及可归因于它的收益。当能力通过平台与嵌入式服务持续交付时，被测量"成功"的那个系统没有清晰边界。'),
        P('Information quality was conceived as accuracy, completeness, and timeliness of output the system produces. For probabilistic systems that are sometimes confidently wrong, quality is a distribution rather than a level, and a perceptual rating collapses that distinction.',
          '信息质量最初被设想为系统产出的准确性、完整性与及时性。对"有时会自信地出错"的概率性系统而言，质量是一个分布而非一个水平，而主观评分抹平了这一区分。'),
      ],
      today=[
        P('Define net benefits for a named stakeholder and level before collecting data, and say so explicitly. Without that the model is a diagram rather than a hypothesis.',
          '应在收集数据之前为指定的利益相关者与层次界定净收益，并明确说明。缺少这一点，该模型只是图示而非假设。'),
        P('If use is mandatory, drop it or report it as compliance. Including mandated use as a success measure inflates the model without informing anything.',
          '若使用是强制的，应删去该指标或将其作为合规来报告。把强制使用当作成功指标会抬高模型却不提供任何信息。'),
      ]),

    # ------------------------------------------------------ task-technology fit
    D('task-technology-fit',
      era='Published 1995 as a corrective to attitude-based adoption models; used steadily since without major revision.',
      era_zh='1995 年作为对态度式采纳模型的纠偏而提出，此后持续使用，未经重大修订。',
      situation=[
        P('Adoption research explained whether people would use a system but not whether using it would help. A system could be enthusiastically adopted and still fail to improve performance.',
          '采纳研究解释了人们是否会使用系统，却没有解释使用它是否有帮助。一个系统可以被热情采纳，却仍无法提升绩效。'),
        P('The argument was that attitude models were answering the wrong question for an organization deciding whether to invest: what matters is whether the technology capabilities match what the task requires.',
          '其论点是：对正在决定是否投资的组织而言，态度模型回答的是错误的问题；真正重要的是技术能力是否与任务需求相匹配。'),
      ],
      argument=[
        P('Fit is the correspondence between task requirements, individual abilities, and technology functionality. High fit produces performance impact; utilization alone does not.',
          '匹配是任务需求、个体能力与技术功能之间的对应。高匹配产生绩效影响，而单靠使用量不会。'),
        P('The model predicts performance impact directly and through utilization, which is what distinguishes it from adoption models: a well-fitting technology helps even where use is mandated and attitude is irrelevant.',
          '模型既直接预测绩效影响，也经由使用量预测——这正是它区别于采纳模型之处：即便使用是强制的、态度无关紧要，高匹配的技术依然有帮助。'),
      ],
      development=[
        P('Integrated models combined it with attitude-based frameworks, on the reasoning that fit explains performance while attitude explains use, and both are needed for a complete account.',
          '整合模型把它与态度式框架结合，理由是匹配解释绩效、态度解释使用，完整解释需要两者。'),
      ],
      debates=[
        Debate('How should fit be operationalized?', '匹配应如何操作化？',
               [Pos('Matching position',
                    'Fit is a distinct construct measured directly by asking users whether the technology suits their tasks.',
                    '匹配是一个独立构念，可通过询问用户"技术是否适合其任务"直接测量。'),
                Pos('Profile position',
                    'Fit is the correspondence between separately measured task and technology profiles, and asking about fit directly measures a global impression instead.',
                    '匹配是分别测量的任务剖面与技术剖面之间的对应；直接询问匹配测到的只是一种整体印象。')],
               'Unresolved, and studies using the two approaches on the same data reach different conclusions.',
               '未决，且在同一数据上使用两种做法的研究得出不同结论。'),
      ],
      theoretical=[
        P('Fit is defined relative to a specified task. A general fit score is not interpretable because it averages across tasks with different requirements.',
          '匹配是相对于特定任务定义的。通用匹配分数不可解读，因为它把需求不同的任务平均在一起。'),
        P('The model treats task requirements as given, though technology adoption frequently changes what the task is, which the framework does not represent.',
          '模型把任务需求当作既定，然而技术采纳经常改变任务本身是什么——而框架并未表达这一点。'),
      ],
      empirical=[
        P('Task characteristics are usually self-reported by the same person who rates performance, so the fit-performance relationship is a within-respondent correlation.',
          '任务特征通常由评定绩效的同一人自评，因此匹配与绩效的关系只是受访者内部的相关。'),
        P('Performance impact is almost always perceived rather than observed, and perceived impact correlates weakly with measured productivity.',
          '绩效影响几乎总是感知而非观察得来，而感知影响与实测生产率的相关很弱。'),
      ],
      temporal=[
        P('The model assumes a technology with fixed functionality that can be matched against a stable task. Configurable and general-purpose systems can be adapted to many tasks, so fit becomes something the user constructs rather than a property to be assessed before adoption.',
          '模型假定技术功能固定，可与稳定任务作匹配。可配置的通用系统能适配多种任务，因此匹配成为用户建构出来的东西，而非采纳前可评估的属性。'),
        P('It was written when the alternative to a system was doing the task manually, so fit could be assessed against a known baseline. Where a system performs part of the task and the human supervises, the task itself is redefined and there is no stable requirement to fit against.',
          '它写作之时，系统的替代方案是人工完成任务，因此匹配可对照已知基准评估。当系统承担部分任务而人类负责监督时，任务本身被重新定义，也就不存在可供匹配的稳定需求。'),
      ],
      today=[
        P('Name the task and measure fit for it. A study of a general-purpose tool needs to specify which use is being evaluated or the construct has no referent.',
          '应指明任务并针对它测量匹配。研究通用工具时必须说明评估的是哪种用途，否则该构念没有指称对象。'),
        P('Where possible use observed performance rather than perceived impact, since the gap between them is largest exactly where the model is most useful.',
          '尽可能使用实测绩效而非感知影响；二者的落差恰恰在该模型最有用的场合最大。'),
      ]),
])
