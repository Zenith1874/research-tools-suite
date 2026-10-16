# -*- coding: utf-8 -*-
"""Deep dives for catalog constructs.

Same schema as the theory dives, different questions. For a construct the blocks
read as: what it is trying to capture, how it came to be defined and measured,
how the measurement evolved, which disputes are open, and which of its limits
are conceptual, which are measurement artefacts, and which are bound to the
workplace the instrument was written for.

Schema helpers live in ``research_catalog_deep_dives``. Content here is written
analysis, not extracted text; scale items are never reproduced.
"""

from research_catalog_deep_dives import D, Debate, P, Pos

CONSTRUCT_DIVES = dict([

    # ---------------------------------------------------------------- autonomy
    D('autonomy',
      era='Operationalized for job design research in the 1970s; carried into motivation and wellbeing research largely unchanged.',
      era_zh='1970 年代为工作设计研究操作化，此后几乎原样沿用于动机与福祉研究。',
      situation=[
        P('Job design research needed a way to say that two jobs producing the same output can differ in how much the worker decides. Autonomy names that difference: the discretion a person has over how, when, and in what order work is done.',
          '工作设计研究需要一种方式来表达：产出相同的两份工作，员工能自行决定的程度可以完全不同。自主性正是命名这一差异——个体对"如何做、何时做、以何种顺序做"所拥有的裁量权。'),
        P('It was deliberately defined as experienced discretion rather than formal authority. A worker can hold a job description full of latitude and still experience none, and it is the experience that predicts motivation.',
          '它被刻意定义为"体验到的裁量"而非正式授权。一名员工的岗位说明书可以写满自由度，实际却毫无体验；而预测动机的是体验，不是文本。'),
      ],
      argument=[
        P('Measurement is almost always self-report on a short scale asking how much freedom the respondent has to decide methods, scheduling, and criteria. These three facets are usually averaged into one score.',
          '测量几乎总是简短的自评量表，询问受访者在方法、时间安排与判断标准上有多大自由度。这三个面向通常被平均为单一分数。'),
        P('The construct sits in the middle of most models: it is an antecedent of engagement and satisfaction, a mediator between job design and outcomes, and a moderator that buffers demands. That versatility is why it appears everywhere, and why its role must be argued rather than assumed in any given study.',
          '该构念在多数模型中处于中间位置：既是投入与满意度的前因，也是工作设计与结果之间的中介，还是缓冲要求的调节变量。这种多功能性使它无处不在，也意味着在任一研究中它的角色必须被论证而非默认。'),
      ],
      development=[
        P('Later work separated method autonomy, scheduling autonomy, and decision-making autonomy, showing they predict different outcomes. Studies that average them lose that resolution.',
          '后续研究把方法自主、时间自主与决策自主区分开，证明它们预测不同的结果。把三者平均的研究会丢失这一分辨率。'),
      ],
      debates=[
        Debate('Is autonomy distinct from related job resources?', '自主性与相关工作资源可区分吗？',
               [Pos('Discriminant concern',
                    'Autonomy, empowerment, job control, and decision latitude are measured with overlapping items and correlate highly enough that they may be one construct under four names.',
                    '自主性、授权、工作控制与决策自由度的题项相互重叠，相关高到可能只是同一构念的四个名字。'),
                Pos('Distinctness position',
                    'They differ in referent: control concerns the work process, empowerment adds a psychological state, and decision latitude includes skill discretion.',
                    '它们的指称不同：控制针对工作过程，授权附加了心理状态，决策自由度还包含技能裁量。')],
               'Unresolved, and it matters: a study that reports autonomy while measuring decision latitude is not replicating what it claims to replicate.',
               '未决，且很重要：以决策自由度测量却报告为自主性的研究，并没有复制它声称复制的东西。'),
      ],
      theoretical=[
        P('More autonomy is treated as monotonically better in most applications, though the original job-design work allowed for growth-need moderation and later work finds costs at very high levels.',
          '多数应用把自主性当作越多越好，尽管最初的工作设计研究允许成长需要的调节，后续研究也发现极高水平存在代价。'),
        P('The construct is defined at the individual level but is often produced by team or unit arrangements, and multilevel structure is frequently ignored.',
          '构念定义在个体层面，实际却常由团队或单元安排所产生，而多层结构经常被忽略。'),
      ],
      empirical=[
        P('Self-report autonomy is measured in the same survey as the outcome it predicts, so common method variance inflates nearly every published coefficient.',
          '自评自主性与它所预测的结果在同一份问卷中测量，共同方法偏差抬高了几乎每一个已发表的系数。'),
        P('Objective and perceived autonomy diverge substantially. Studies that need the objective construct — for example evaluating a job redesign — should not rely on a perception scale alone.',
          '客观自主性与感知自主性差异很大。需要客观构念的研究（例如评估一次工作再设计）不应仅依赖感知量表。'),
      ],
      temporal=[
        P('The scales were written for a supervised workplace where the alternative to discretion was a human instruction. Algorithmic allocation can leave every scale item nominally satisfied — the worker still chooses the order and the method — while removing the discretion that actually matters, such as whether to accept the task at all.',
          '量表写给的是"有人监督"的职场，那里裁量的对立面是人的指令。算法派单可以让每个题项在名义上都成立——员工仍可选择顺序与方法——却拿走了真正重要的裁量，比如是否接受这项任务。'),
        P('Remote and hybrid work moved scheduling discretion into the home, where it is entangled with domestic constraint. A high scheduling-autonomy score no longer means the same thing it meant when the scale was validated on office workers.',
          '远程与混合工作把时间自主移入家庭，与家务约束纠缠在一起。高时间自主分数的含义，已不同于该量表在办公室员工身上完成验证时的含义。'),
      ],
      today=[
        P('Still one of the best-supported predictors of engagement and wellbeing, and worth keeping in almost any job-design model.',
          '它仍是投入与福祉最有支持的预测变量之一，几乎任何工作设计模型都值得保留它。'),
        P('In algorithmic settings, measure the specific discretion at stake rather than using a generic scale, and say which facet you mean. A generic score will register autonomy that workers do not experience.',
          '在算法情境中，应测量真正受影响的具体裁量权、并说明指的是哪个面向，而不是套用通用量表。通用分数会测出员工并未体验到的自主性。'),
      ]),

    # ----------------------------------------------------------------- burnout
    D('burnout',
      era='Named in the 1970s from practitioner observation; instrumented in 1981 and redefined by WHO classification in 2019.',
      era_zh='1970 年代由实务观察命名，1981 年形成量表，2019 年经 WHO 分类重新界定。',
      situation=[
        P('The concept began outside academia, among people running helping services who noticed that committed staff were becoming exhausted and detached in a patterned way rather than randomly burning out.',
          '这一概念起源于学界之外：助人服务机构的从业者注意到，投入的员工会以某种规律的方式变得耗竭与疏离，而非随机崩溃。'),
        P('Research needed to distinguish it from depression and from ordinary fatigue, and to tie it specifically to the work situation rather than to the person, because the practical claim was that the job was producing it.',
          '研究需要把它与抑郁和一般疲劳区分开，并把它明确归因于工作情境而非个人特质——因为其现实主张是：是工作在制造它。'),
      ],
      argument=[
        P('The dominant operationalization has three components: emotional exhaustion, depersonalization or cynicism toward the work and its recipients, and reduced personal accomplishment.',
          '主流操作化包含三个成分：情绪耗竭；对工作及其对象的去人格化或犬儒；以及个人成就感降低。'),
        P('Exhaustion carries most of the predictive weight and correlates most strongly with health and turnover outcomes. Reduced accomplishment behaves differently enough from the other two that some argue it does not belong in the same construct.',
          '耗竭承担了大部分预测力，与健康和离职结果的相关最强。成就感降低的表现与前两者差异明显，以至于有人主张它不属于同一构念。'),
      ],
      development=[
        P('Alternative instruments were developed to address the three-component structure and to make the construct applicable outside the human services it was built in.',
          '为回应三成分结构问题、并使构念适用于其诞生领域（助人服务）之外，学界发展出多种替代量表。'),
        P('The 2019 WHO classification framed it as an occupational phenomenon rather than a medical condition, which sharpened the claim that the cause is situational.',
          '2019 年 WHO 将其界定为职业现象而非医学状况，这强化了"成因在情境"这一主张。'),
      ],
      debates=[
        Debate('Is burnout distinct from depression?', '倦怠与抑郁可区分吗？',
               [Pos('Distinctness position',
                    'Burnout is work-specific and situationally caused, and its trajectory follows job conditions rather than generalizing across life domains.',
                    '倦怠是工作特定、由情境造成的，其轨迹随工作条件变化，而不会泛化到生活各领域。'),
                Pos('Overlap position',
                    'Exhaustion items correlate with depression scales strongly enough that the two may not be separable at the measurement level.',
                    '耗竭题项与抑郁量表的相关强到在测量层面二者可能无法分离。')],
               'Long-running and unresolved; it has practical stakes for whether the response is organizational redesign or clinical treatment.',
               '长期未决；它关系到应对方式究竟是组织再设计还是临床治疗，具有现实后果。'),
      ],
      theoretical=[
        P('Three components with different antecedents and different consequences are summed into one score in much applied work, which discards the structure the construct was built on.',
          '三个前因与后果各异的成分，在大量应用研究中被加总为单一分数，从而丢弃了构念赖以建立的结构。'),
        P('The construct is defined as situationally caused, but the standard measure asks the individual about their own state, which cannot distinguish a demanding job from a vulnerable person.',
          '构念被定义为情境所致，标准测量却询问个体自身状态，无法区分"高要求的工作"与"脆弱的个人"。'),
      ],
      empirical=[
        P('Almost all evidence is cross-sectional self-report, so the causal direction between job conditions and burnout is rarely established rather than assumed.',
          '几乎全部证据都是横截面自评，工作条件与倦怠之间的因果方向很少被确立，多是被假定。'),
        P('Cut-off scores for who is burned out vary across studies and instruments, so prevalence figures are not comparable and should be treated with caution.',
          '"谁算倦怠"的临界值因研究与量表而异，因此患病率数字不可比，引用时应谨慎。'),
      ],
      temporal=[
        P('The construct was built on human-service work with face-to-face recipients, which is where depersonalization has an obvious referent. Applied to software engineers or analysts, the depersonalization component often has no clear object and the instrument measures something looser than it did originally.',
          '构念建立在与服务对象面对面的助人工作之上，那里"去人格化"有明确指向。用于软件工程师或分析师时，该成分往往没有清晰对象，量表所测的东西比最初宽泛得多。'),
        P('Recovery was assumed to happen away from work. Where work is remote and continuously addressable, the boundary that made the exhaustion/recovery cycle legible is weaker, and instruments written before that shift do not ask about it.',
          '恢复被假定发生在工作之外。当工作远程化、随时可触达时，使"耗竭—恢复"周期得以辨识的边界被削弱，而在此转变之前编写的量表并不询问这一点。'),
      ],
      today=[
        P('Report the components separately, or justify the composite. Exhaustion alone is often the honest dependent variable and behaves better than the sum.',
          '应分别报告三个成分，或论证为何可以合成。仅用耗竭往往是更诚实的因变量，其表现也优于加总分。'),
        P('If the claim is that the job causes it, the design has to observe job conditions independently of the person reporting the burnout.',
          '若主张是"工作导致倦怠"，研究设计就必须独立于报告倦怠者本人来观察工作条件。'),
      ]),

    # ------------------------------------------------------------------- trust
    D('trust',
      era='Integrated into a standard organizational model in 1995; applied to technology and automation from the 2000s.',
      era_zh='1995 年被整合为标准的组织研究模型，2000 年代起应用于技术与自动化情境。',
      situation=[
        P('Trust was studied across psychology, sociology, and economics with incompatible definitions — a personality trait, a rational expectation, an institutional condition — which made findings impossible to accumulate.',
          '信任曾在心理学、社会学与经济学中以互不兼容的定义被研究——人格特质、理性预期、制度条件——使得研究结果无法累积。'),
        P('The integration that took hold defined trust as a willingness to be vulnerable, separating it from the trustworthiness of the other party and from the risk-taking behaviour that follows.',
          '最终确立的整合把信任定义为"愿意让自己处于易受影响的状态"，并将其与对方的可信度、以及随之而来的冒险行为区分开。'),
      ],
      argument=[
        P('The model separates three things researchers had been conflating: perceived trustworthiness, judged on ability, benevolence, and integrity; trust itself, the willingness to be vulnerable given that judgement; and risk taking in the relationship, the behaviour that follows.',
          '该模型把研究者长期混淆的三件事分开：可信度感知，依据能力、善意与正直作出判断；信任本身，即在该判断下愿意承受脆弱；以及关系中的冒险行为，即随之发生的行动。'),
        P('The separation matters because an intervention can raise perceived ability without raising benevolence, and the two produce different willingness under different kinds of risk.',
          '这一区分很重要：一项干预可能提升能力感知而不提升善意感知，二者在不同风险情境下产生不同的意愿。'),
      ],
      development=[
        P('Automation and algorithmic contexts imported the model but found the three trustworthiness dimensions transfer unevenly: ability maps onto system accuracy, while benevolence and integrity have no obvious referent in a system with no intentions.',
          '自动化与算法情境引入了该模型，却发现三个可信度维度迁移得并不均匀：能力可对应系统准确性，而善意与正直在"没有意图"的系统中缺乏明显指称。'),
      ],
      debates=[
        Debate('Can a system be trusted in the same sense as a person?', '系统能在与人相同的意义上被信任吗？',
               [Pos('Continuity position',
                    'People demonstrably form trust-like expectations about systems, and the same three dimensions predict reliance behaviour.',
                    '人们确实会对系统形成类信任的预期，且同样三个维度可预测依赖行为。'),
                Pos('Category position',
                    'Benevolence and integrity presuppose intent; applying them to a system measures beliefs about its designers or a projection, not about the system.',
                    '善意与正直以意图为前提；把它们用于系统，测到的是对设计者的信念或一种投射，而非对系统本身的判断。')],
               'Open, and consequential for how automation-trust results should be interpreted.',
               '未决，且直接影响自动化信任研究结果的解读方式。'),
      ],
      theoretical=[
        P('Trust, trustworthiness, and trusting behaviour are still routinely used interchangeably in applied work despite the model that separated them.',
          '尽管已有模型将三者分开，应用研究中信任、可信度与信任行为仍常被混用。'),
        P('The construct is dyadic but is often measured as a general disposition, which loses the referent that makes it meaningful.',
          '该构念本是二元关系性的，却常被当作一般倾向来测量，从而丢失了使其有意义的指称对象。'),
      ],
      empirical=[
        P('Trust and its supposed consequences are typically collected in one survey wave, so the willingness-to-be-vulnerable claim is established by association rather than by observing vulnerability.',
          '信任与其假定后果通常在同一波问卷中收集，因此"愿意承受脆弱"的主张只是由关联确立，而非通过观察脆弱行为确立。'),
        P('Behavioural trust games and survey trust scales correlate weakly, which suggests they are not measuring the same construct.',
          '行为信任博弈与问卷信任量表的相关很弱，这提示二者测的可能不是同一构念。'),
      ],
      temporal=[
        P('The model assumes an identifiable counterparty whose ability, benevolence, and integrity can be judged. In algorithmic and platform settings the counterparty is distributed across a system, its designers, and the firm deploying it, and the respondent may be answering about a different one than the researcher intends.',
          '模型假定存在可辨识的对象，其能力、善意与正直可被判断。在算法与平台情境中，对象分散于系统、设计者与部署方之间，受访者所回答的对象可能与研究者设想的并不相同。'),
        P('It was formulated when the trusted party was stable between interactions. Systems that change behaviour between versions give the trustor a moving target, which the model treats as a fixed object.',
          '它成形之时，被信任方在多次互动之间是稳定的。会随版本改变行为的系统给了信任方一个移动靶，而模型把它当作固定对象处理。'),
      ],
      today=[
        P('Name the referent explicitly — trust in what, judged on which dimension — before choosing an instrument. Most confusion in this literature is referent confusion.',
          '在选择量表之前，先明确指称对象——信任什么、依据哪个维度判断。这一文献中的多数混乱都是指称混乱。'),
        P('For automation studies, consider reporting the trustworthiness dimensions separately rather than a composite; ability and integrity often move in opposite directions when a system is accurate but opaque.',
          '自动化研究中，宜分别报告可信度各维度而非合成分；当系统准确却不透明时，能力与正直往往朝相反方向变动。'),
      ]),

    # ------------------------------------------------------- employee engagement
    D('employee-engagement',
      era='Introduced academically in 1990; instrumented in 2002 and popularized in parallel by consultancies.',
      era_zh='1990 年进入学术研究，2002 年形成量表，同期被咨询业以另一条线路推广。',
      situation=[
        P('Satisfaction predicted turnover reasonably but performance poorly. The field wanted a state that captured investment of energy in the work role rather than contentment with it.',
          '满意度能较好预测离职，却难以预测绩效。学界需要一个刻画"在工作角色中投入能量"的状态，而非对工作的满足感。'),
        P('The academic construct and the practitioner construct developed in parallel and were never fully reconciled, which is the source of most confusion around the term.',
          '学术构念与实务构念平行发展、从未完全调和，这正是该术语周边多数混乱的根源。'),
      ],
      argument=[
        P('The academic version defines engagement as a positive work-related state with three facets: vigor, energy and persistence; dedication, involvement and significance; and absorption, full concentration in the work.',
          '学术版本把敬业界定为一种积极的工作相关状态，含三个面向：活力（能量与坚持）、奉献（投入与意义感）、专注（全神贯注于工作）。'),
        P('It is explicitly positioned as the positive antipode of burnout, which is why the two are usually studied within the same framework and share antecedents in opposite directions.',
          '它被明确定位为倦怠的积极对立面，这也是二者通常在同一框架下研究、并共享方向相反的前因的原因。'),
      ],
      development=[
        P('Practitioner measures folded in satisfaction, commitment, and intention to stay, producing indices that predict outcomes partly because they already contain them.',
          '实务量表把满意度、承诺与留任意向一并纳入，形成的指数之所以能预测结果，部分原因是它本就包含了结果。'),
      ],
      debates=[
        Debate('Is engagement distinct from what preceded it?', '敬业与既有构念可区分吗？',
               [Pos('Redundancy critique',
                    'Engagement correlates so highly with job involvement, affective commitment, and satisfaction that it may be old wine relabelled.',
                    '敬业与工作卷入、情感承诺、满意度相关极高，可能只是旧概念换了标签。'),
                Pos('Distinctness position',
                    'Absorption in particular has no counterpart in the older constructs, and engagement predicts performance where satisfaction does not.',
                    '尤其"专注"在旧构念中没有对应物，且敬业能预测绩效而满意度不能。')],
               'Partially settled in favour of distinctness at the facet level, but composite measures remain hard to separate from commitment.',
               '在面向层面基本判定为可区分，但合成分数仍难与承诺分离。'),
      ],
      theoretical=[
        P('The three facets are theorized as a single state but behave differently: absorption is closest to flow and has weaker links to organizational outcomes than vigor.',
          '三个面向在理论上被视为同一状态，实际表现却不同：专注最接近心流，与组织结果的联系弱于活力。'),
        P('It is a person-level state produced largely by job and unit conditions, and treating it as an individual attribute invites intervention aimed at the wrong level.',
          '它是主要由工作与单元条件所产生的个体状态；把它当作个体属性，会导致干预瞄错层次。'),
      ],
      empirical=[
        P('Nearly all evidence is same-source, same-wave self-report against self-rated performance, which is the weakest available design for the central claim.',
          '几乎全部证据都是同源、同波次的自评，且对照自评绩效，这是支撑其核心主张最弱的设计。'),
        P('Practitioner indices used as the measure make the finding partly tautological when the outcome is retention or satisfaction.',
          '当结果变量是留任或满意度时，采用实务指数作为测量会使发现在部分程度上成为同义反复。'),
      ],
      temporal=[
        P('The scale assumes a bounded work role the respondent can hold in mind while answering. Portfolio, platform, and multi-employer arrangements give the respondent no single role to be engaged in, and the instrument does not ask which one they had in mind.',
          '量表假定受访者作答时心中有一个边界清晰的工作角色。组合式、平台化与多雇主安排使受访者并无单一角色可供投入，而量表并不询问他们想的是哪一个。'),
        P('Vigor and absorption items were written before continuous connectivity. Sustained absorption now reads as a positive score even where it reflects an inability to disengage, which the construct treats as its opposite.',
          '活力与专注题项写于持续在线之前。如今持续的专注即使反映的是"无法脱离"，也会被记为正向分数，而构念本身把后者视为其对立面。'),
      ],
      today=[
        P('State which definition you are using and cite the matching instrument. A study that measures a consultancy index and discusses the academic construct is not testing the theory it cites.',
          '应明确采用哪一定义并引用相匹配的量表。用咨询业指数测量却讨论学术构念的研究，并未检验它所引用的理论。'),
        P('Where possible pair self-report with an outcome the respondent does not also rate, since the same-source problem is the main limitation on this literature.',
          '尽可能把自评与"非由受访者自评的结果"配对，因为同源问题是这一文献的主要局限。'),
      ]),

    # ------------------------------------------------------------- firm performance
    D('firm-performance',
      era='Used as a dependent variable throughout the history of strategy research; measurement debated continuously since the 1980s.',
      era_zh='贯穿战略研究史的因变量，其测量自 1980 年代起持续存在争论。',
      situation=[
        P('Strategy research needed a common outcome so that competing explanations could be compared. Firm performance became that outcome largely by default rather than by conceptual argument.',
          '战略研究需要一个共同结果变量，以便比较相互竞争的解释。企业绩效在很大程度上是默认成为该结果的，而非经由概念论证确立。'),
        P('The problem is that performance is not one thing. Accounting returns, market valuation, growth, and survival answer different questions and frequently disagree about the same firm.',
          '问题在于绩效并非单一事物。会计回报、市场估值、增长与存续回答的是不同问题，且对同一家企业常常给出不一致的答案。'),
      ],
      argument=[
        P('Accounting measures report realized past performance and are backward looking, comparable within an industry, and manipulable through reporting choices.',
          '会计指标报告已实现的过往绩效，是向后看的，在同一产业内可比，且可通过报表选择被操纵。'),
        P('Market measures embed expectations about the future and are forward looking, but they reflect what investors believe rather than what the firm achieved, and they are unavailable for private firms.',
          '市场指标内嵌对未来的预期，是向前看的；但它反映的是投资者的信念而非企业的实际成就，且私营企业无法获得。'),
      ],
      development=[
        P('Multi-dimensional treatments emerged, arguing that performance should be modelled as a set of related outcomes with different stakeholders rather than reduced to one number.',
          '多维处理方式随之出现，主张绩效应被建模为面向不同利益相关者的一组相关结果，而非归约为单一数字。'),
      ],
      debates=[
        Debate('Should performance measures be combined?', '绩效指标应当合成吗？',
               [Pos('Composite position',
                    'A single index reduces measurement error and lets studies be compared across contexts.',
                    '单一指数可降低测量误差，并使不同情境的研究得以比较。'),
                Pos('Separation position',
                    'Accounting and market measures answer different questions and often diverge; averaging them produces a number with no clear referent.',
                    '会计与市场指标回答不同问题且经常背离；把它们平均会得到一个没有明确指称的数字。')],
               'Open. Most methodological guidance now favours reporting measures separately and explaining divergence.',
               '未决。当前多数方法学建议倾向于分别报告并解释其背离。'),
      ],
      theoretical=[
        P('The construct has no agreed definition independent of its measures, so the theoretical claim is usually smuggled in through the choice of indicator.',
          '该构念缺乏独立于其测量的公认定义，理论主张往往经由指标选择被夹带进来。'),
        P('Performance relative to what — history, aspiration, competitors — is a theoretical choice that changes the result and is frequently left implicit.',
          '"相对于什么"的绩效——历史、抱负还是竞争对手——是一个会改变结果的理论选择，却常常被隐而不宣。'),
      ],
      empirical=[
        P('Survivorship bias is pervasive: firms that failed are absent from most panels, which biases estimates of what predicts performance upward.',
          '存活偏差普遍存在：失败企业不在多数面板样本中，这会向上偏倚"什么能预测绩效"的估计。'),
        P('Industry and year effects account for a large share of variance, and studies that omit them attribute to strategy what belongs to context.',
          '产业与年度效应解释了很大一部分方差；忽略它们的研究会把属于情境的部分归功于战略。'),
      ],
      temporal=[
        P('The measurement toolkit was built for firms whose value sits in reported assets and earnings. Where value is concentrated in intangibles, data, and user relationships that accounting standards recognize inconsistently, book-based measures capture progressively less of what the firm is.',
          '这套测量工具是为"价值体现在报表资产与盈利中"的企业设计的。当价值集中于会计准则认定不一致的无形资产、数据与用户关系时，账面指标能捕捉的部分越来越少。'),
        P('Platform and ecosystem firms may pursue deliberate losses for position, which older accounting-based frameworks read as poor performance rather than as strategy.',
          '平台与生态型企业可能为占位而刻意亏损，而基于会计的旧框架会把这读作绩效不佳，而非战略。'),
      ],
      today=[
        P('Choose the measure from the theory, not from availability, and state what the theory predicts should move. A framework about competitive position and one about investor expectations do not predict the same indicator.',
          '应从理论出发选择指标，而非从数据可得性出发，并说明理论预测哪一项会变动。关于竞争位置的框架与关于投资者预期的框架，预测的并不是同一个指标。'),
        P('Report at least one accounting and one market measure where both exist, and treat divergence as a finding rather than a nuisance.',
          '在两者都可得时至少各报告一个会计指标与一个市场指标，并把二者背离当作发现而非麻烦。'),
      ]),

    # ---------------------------------------------------------------- innovation
    D('innovation',
      era='Studied since the 1960s; measurement dominated by patent and R&D data from the 1980s.',
      era_zh='1960 年代起被研究，1980 年代起测量以专利与研发数据为主导。',
      situation=[
        P('Innovation research needed a countable outcome. Patents and R&D expenditure were available at scale, comparable across firms, and already collected, so they became the measure by availability rather than by fit.',
          '创新研究需要一个可计数的结果。专利与研发支出规模化可得、跨企业可比、且已有人收集，于是它们因"可得"而非因"贴切"成为测量指标。'),
        P('That choice shaped the field: what could be counted became what was studied, and innovation that leaves no patent trail was systematically underrepresented.',
          '这一选择塑造了整个领域：可计数之物成为被研究之物，而不留专利痕迹的创新被系统性地低估。'),
      ],
      argument=[
        P('The construct spans an input, a process, and an output. R&D spending measures input, patent counts measure a legally filtered output, and new-product announcements measure a commercially filtered one; none of them measures the process.',
          '该构念横跨投入、过程与产出。研发支出测的是投入，专利数测的是经法律筛选的产出，新产品公告测的是经商业筛选的产出；三者都不测量过程。'),
        P('Product, process, and business-model innovation have different antecedents and different consequences, and collapsing them into one variable hides which one a result is about.',
          '产品创新、流程创新与商业模式创新的前因与后果各不相同；把它们合并为一个变量会掩盖某一结果究竟关乎哪一种。'),
      ],
      development=[
        P('Citation-weighted patents and text-based measures from filings and product descriptions were introduced to distinguish significant innovations from routine ones.',
          '引用加权专利以及基于申报文件与产品描述的文本指标被引入，用以区分重要创新与常规创新。'),
      ],
      debates=[
        Debate('Do patents measure innovation?', '专利能测量创新吗？',
               [Pos('Practical position',
                    'Patents are the only large-scale, long-run, internationally comparable indicator available, and citation weighting handles quality differences.',
                    '专利是唯一大规模、长时段、国际可比的指标，引用加权可处理质量差异。'),
                Pos('Validity critique',
                    'Propensity to patent varies enormously by industry and strategy; firms that protect through secrecy or speed appear uninnovative by construction.',
                    '申请专利的倾向因产业与战略差异极大；以保密或速度作为保护手段的企业，按定义就显得没有创新。')],
               'Open. The measure is retained for coverage while its validity limits are increasingly acknowledged in print.',
               '未决。该指标因覆盖面而被保留，但其效度局限在文献中被越来越明确地承认。'),
      ],
      theoretical=[
        P('Novelty is relative to a reference set — the firm, the market, or the world — and studies frequently leave the reference implicit, which makes results incomparable.',
          '新颖性是相对于某个参照集而言的——企业、市场还是全世界——而研究常把参照隐而不宣，使结果无法比较。'),
        P('Innovation is treated as an unqualified good in most models, though the same measures count failed and value-destroying innovation identically.',
          '多数模型把创新视为无条件的好事，尽管同样的指标会把失败的、毁损价值的创新等同计数。'),
      ],
      empirical=[
        P('R&D and patent data are missing or unreliable for private firms, services, and emerging economies, so the evidence base is skewed toward large listed manufacturers.',
          '私营企业、服务业与新兴经济体的研发与专利数据缺失或不可靠，因此证据基础偏向大型上市制造企业。'),
        P('Patent counts lag the underlying activity by years, and studies rarely align the lag with the theorized mechanism.',
          '专利计数滞后于其背后的活动数年，而研究很少让滞后与所设想的机制在时间上对齐。'),
      ],
      temporal=[
        P('The measurement apparatus assumes innovation is discrete, documented, and legally protected. Software and model-based innovation is often continuous, undocumented in patents, and protected by speed or data access instead, so a firm can be highly innovative and score near zero.',
          '这套测量装置假定创新是离散的、有文档的、受法律保护的。软件与基于模型的创新往往是连续的、不体现在专利中、并以速度或数据获取而非法律加以保护——因此一家企业可以极具创新性却得分近乎为零。'),
        P('The frameworks were built when the innovating unit was the firm. Where innovation happens across an ecosystem or on top of a shared foundation model, attributing it to a single firm is a measurement decision the theory does not license.',
          '这些框架建立时，创新的单位是企业。当创新发生在生态系统之中、或建立在共享基础模型之上时，把它归属于单一企业只是一项测量决定，而非理论所许可的推论。'),
      ],
      today=[
        P('Pick the measure that matches the theorized mechanism and defend it. If the argument is about recombination, a raw count is the wrong instrument.',
          '应选择与所设想机制相匹配的指标并加以论证。若论证关乎"重组"，原始计数就是错误的工具。'),
        P('For software and AI settings, patent-based designs will systematically miss the phenomenon; text or release-based measures are usually closer to the construct.',
          '在软件与 AI 情境中，基于专利的设计会系统性地错过现象；基于文本或版本发布的指标通常更接近构念。'),
      ]),

    # ------------------------------------------------------------ information asymmetry
    D('information-asymmetry',
      era='Formalized in economics in the 1970s; imported into finance, accounting, and strategy from the 1980s.',
      era_zh='1970 年代在经济学中形式化，1980 年代起被引入金融、会计与战略研究。',
      situation=[
        P('Market models assumed participants shared the relevant information. Once that assumption was dropped, a family of results followed showing that markets can fail even when everyone behaves rationally.',
          '市场模型曾假定参与者共享相关信息。一旦放弃该假定，随之而来的一系列结论表明：即使所有人都理性行事，市场仍可能失灵。'),
        P('The construct gave a name to the condition that generates adverse selection before contracting and moral hazard after it, and it underpins signaling, agency, and much of disclosure research.',
          '该构念为"缔约前产生逆向选择、缔约后产生道德风险"的条件命名，是信号理论、代理理论与大量披露研究的基础。'),
      ],
      argument=[
        P('One party holds material information the other lacks and cannot cheaply acquire. The asymmetry has to be material to the transaction and costly to resolve, or it is merely a difference in knowledge with no economic consequence.',
          '一方掌握而另一方缺乏、且无法低成本获取的重要信息，构成信息不对称。该不对称必须对交易重要且解决成本高昂，否则只是没有经济后果的知识差异。'),
        P('Its consequences depend on timing: hidden information before the contract drives selection effects, while hidden action after it drives incentive effects. Conflating the two is the most common analytical error.',
          '其后果取决于时点：缔约前的隐藏信息驱动选择效应，缔约后的隐藏行动驱动激励效应。混淆二者是最常见的分析错误。'),
      ],
      development=[
        P('Empirical work developed proxies — bid-ask spreads, analyst forecast dispersion, disclosure quality scores — each capturing a different facet and none capturing the construct directly.',
          '经验研究发展出若干代理指标——买卖价差、分析师预测离散度、披露质量评分——各自捕捉不同面向，且都不直接测量该构念。'),
      ],
      debates=[
        Debate('Do the standard proxies measure asymmetry or something else?', '标准代理指标测的是不对称还是别的东西？',
               [Pos('Proxy defence',
                    'Spreads and forecast dispersion respond to information environments in the predicted direction across many settings.',
                    '价差与预测离散度在众多情境中都按预测方向随信息环境变化。'),
                Pos('Proxy critique',
                    'They also respond to liquidity, volatility, and attention, so a finding may reflect trading conditions rather than an information gap.',
                    '它们同样随流动性、波动性与关注度变化，因此发现可能反映的是交易状况而非信息差距。')],
               'Open. Studies increasingly report several proxies and treat agreement among them as the evidence.',
               '未决。研究越来越多地同时报告多个代理指标，并把它们之间的一致性视为证据。'),
      ],
      theoretical=[
        P('Asymmetry is defined relative to a specific decision, but is often treated as a general property of a firm or market, which loses the transaction it was defined against.',
          '不对称是相对于某一具体决策定义的，却常被当作企业或市场的一般属性，从而丢失了它所对应的交易。'),
        P('The framework assumes the informed party knows what it knows. Where the relevant information exists in a model or a dataset that nobody has interpreted, the classical setup does not apply cleanly.',
          '框架假定掌握信息的一方知道自己掌握了什么。当相关信息存在于无人解读过的模型或数据集中时，经典设定无法干净适用。'),
      ],
      empirical=[
        P('No direct measure exists; every empirical claim rests on a proxy whose validity is contested, and results can flip with the proxy chosen.',
          '不存在直接测量；每一个经验主张都依赖效度有争议的代理指标，而结论可能随所选代理而反转。'),
        P('Disclosure is endogenous — firms disclose more when they benefit from doing so — so disclosure-based proxies are jointly determined with the outcomes they predict.',
          '披露是内生的——企业在有利时才多披露——因此基于披露的代理与其所预测的结果是共同决定的。'),
      ],
      temporal=[
        P('The classical setup assumes information is scarce and costly to acquire. Where filings, reviews, and behavioural traces are abundant, the binding constraint has moved from access to attention and interpretation, which the construct does not model.',
          '经典设定假定信息稀缺、获取昂贵。当申报文件、评价与行为痕迹大量存在时，真正的约束已从"获取"转向"注意与解读"，而该构念并未对此建模。'),
        P('It assumes the asymmetry runs from the informed firm to the uninformed outsider. Platforms observing user behaviour at scale reverse that direction for many transactions, and the standard proxies are not built to detect asymmetry in that direction.',
          '它假定不对称是从掌握信息的企业指向不知情的外部人。大规模观察用户行为的平台在许多交易中反转了这一方向，而标准代理指标并非为检测该方向的不对称而设计。'),
      ],
      today=[
        P('Specify the decision and the direction: who lacks what, at what moment, relative to which choice. Most weak applications skip this and use a proxy as if it were the construct.',
          '应明确决策与方向：谁在何时、相对于哪个选择、缺少什么信息。多数薄弱应用跳过这一步，把代理指标直接当作构念使用。'),
        P('Report more than one proxy. Agreement across proxies with different confounds is the strongest evidence available in this literature.',
          '应报告多个代理指标。混淆因素不同的多个代理彼此一致，是这一文献中最强的证据形式。'),
      ]),

    # ------------------------------------------------------------------ legitimacy
    D('legitimacy',
      era='Central to institutional theory from 1977; given an explicit typology in 1995.',
      era_zh='自 1977 年起成为制度理论核心，1995 年获得明确的类型学界定。',
      situation=[
        P('Institutional theory needed to explain why organizations adopt practices with no efficiency benefit. Legitimacy was the proposed reason: conformity secures the acceptance on which resources and survival depend.',
          '制度理论需要解释组织为何采纳没有效率收益的做法。合法性是给出的答案：顺从换来接受，而资源与存续依赖于这种接受。'),
        P('Without an independent definition, the explanation risked circularity, so later work specified what legitimacy is and where it comes from rather than inferring it from adoption.',
          '若缺乏独立定义，该解释就有循环之虞；因此后续研究转而界定合法性是什么、从何而来，而不是从采纳行为反推。'),
      ],
      argument=[
        P('Legitimacy is a generalized perception that an entity actions are desirable and appropriate within a socially constructed system of norms and beliefs. It is held by an audience, not by the organization.',
          '合法性是一种普遍化的感知：在社会建构的规范与信念体系中，某主体的行为被认为是可取且适当的。它由受众持有，而非组织自身持有。'),
        P('The standard typology separates pragmatic legitimacy, resting on audience self-interest; moral legitimacy, resting on normative approval; and cognitive legitimacy, resting on taken-for-grantedness. They are gained, maintained, and repaired by different means.',
          '标准类型学区分三种：实用合法性，基于受众自身利益；道德合法性，基于规范认可；认知合法性，基于理所当然性。三者的获取、维持与修复方式各不相同。'),
      ],
      development=[
        P('Work on legitimacy repair and on the legitimation of new categories extended the construct from a static condition to a process organizations actively manage.',
          '关于合法性修复与新类别正当化的研究，把该构念从静态状态扩展为组织主动管理的过程。'),
      ],
      debates=[
        Debate('Can legitimacy be measured independently of its effects?', '合法性能独立于其效果被测量吗？',
               [Pos('Circularity critique',
                    'If legitimacy is inferred from survival, resource access, or adoption, then the claim that it produces those outcomes cannot fail.',
                    '若合法性是从存续、资源获取或采纳中推断出来的，那么"合法性带来这些结果"就不可能被推翻。'),
                Pos('Measurement position',
                    'Audience judgements can be observed directly through media coverage, ratings, endorsements, and survey evidence.',
                    '受众判断可以通过媒体报道、评级、背书与问卷证据被直接观察。')],
               'Open in practice; direct audience measurement is now available but remains the minority approach.',
               '实践中未决；直接测量受众判断已经可行，但仍属少数做法。'),
      ],
      theoretical=[
        P('Legitimacy is audience-specific, and an organization can be legitimate to regulators while illegitimate to users. Studies that report legitimacy without naming the audience are underspecified.',
          '合法性是受众特定的：一个组织可能对监管者合法、对用户不合法。未指明受众就报告合法性的研究，界定不足。'),
        P('The three types are analytically distinct but empirically entangled, and most studies do not separate them.',
          '三种类型在分析上可区分，在经验上却相互纠缠，多数研究并未加以分离。'),
      ],
      empirical=[
        P('Media sentiment is the most common proxy and conflates legitimacy with salience: an organization can be widely covered and widely condemned.',
          '媒体情感是最常用的代理，它把合法性与显著度混为一谈：一个组织可以被广泛报道同时被广泛谴责。'),
        P('Legitimacy and reputation are measured with overlapping indicators despite being different constructs — one is about conformity to norms, the other about relative standing.',
          '合法性与声誉尽管是不同构念，却以重叠的指标测量——前者关乎对规范的顺从，后者关乎相对位次。'),
      ],
      temporal=[
        P('The construct assumes a field with identifiable audiences whose norms are relatively settled. Where audiences are fragmented and a practice can be legitimate to one platform community and illegitimate to another simultaneously, a single legitimacy score has no clear referent.',
          '该构念假定场域中存在可辨识的受众，其规范相对稳定。当受众碎片化、某做法可以同时对一个平台社群合法而对另一个不合法时，单一的合法性分数没有明确指称。'),
        P('It was theorized before audience judgement was continuously visible and quantified. Ratings, review scores, and public metrics now make legitimacy partly an observable number, which changes how organizations manage it and what researchers are actually measuring.',
          '它成形于受众判断尚未被持续可见地量化之时。如今评级、评价分数与公开指标使合法性部分地成为可观察数字，这既改变了组织的管理方式，也改变了研究者实际测到的东西。'),
      ],
      today=[
        P('Name the audience and the type before choosing an indicator. Most disagreement in this literature dissolves once those two are specified.',
          '在选择指标前先指明受众与类型。这一文献中的多数分歧，在这两点被明确后即告消解。'),
        P('Where audience judgement is directly observable, measure it directly rather than inferring legitimacy from the outcome it is supposed to explain.',
          '当受众判断可直接观察时，应直接测量，而不是从它本应解释的结果反推合法性。'),
      ]),
])
