# -*- coding: utf-8 -*-
"""Deep dives for catalog methods, batch 4.

The two workhorse regressions, one more design-based estimator, the two text
representation methods, and the remaining fieldwork method. With these the method
catalog is complete except for the experimental variants and a few computational
entries.

Schema helpers live in ``research_catalog_deep_dives``.
"""

from research_catalog_deep_dives import D, Debate, P, Pos

METHOD_DIVES_B4 = dict([

    # ------------------------------------------------------------- OLS regression
    D('ols-regression',
      era='The default quantitative tool for a century; its interpretation reframed by the credibility revolution from the 1990s.',
      era_zh='一个世纪以来的默认量化工具，其解读方式自 1990 年代起被"可信性革命"重新框定。',
      situation=[
        P('Research needed a way to describe how an outcome varies with several factors at once, and to say how much of the variation each accounts for holding the others constant.',
          '研究需要一种方式来描述结果如何随多个因素同时变化，并说明在其他因素不变时每个因素解释了多少变异。'),
        P('Least squares supplied it with an estimator that is computable, has known properties under stated assumptions, and produces a coefficient with a clear arithmetic meaning.',
          '最小二乘提供了这样的估计量：可计算、在给定假定下性质已知，且产生的系数具有清晰的算术含义。'),
      ],
      argument=[
        P('The coefficient is a conditional comparison: the average difference in the outcome between observations that differ by one unit in the regressor and are identical on the included controls.',
          '系数是一种条件比较：在所纳入控制变量上相同、而该自变量相差一单位的观测之间，结果的平均差异。'),
        P('That is a descriptive statement about the data. Whether it is also a causal statement depends entirely on whether the included controls are sufficient, which is an argument about the world rather than a property of the estimator.',
          '这是关于数据的描述性陈述。它是否同时是因果陈述，完全取决于所纳入的控制变量是否充分——而这是关于世界的论证，不是估计量的性质。'),
        P('The assumptions are ordered by consequence. Exogeneity determines whether the estimate means anything; homoskedasticity and normality affect only the standard errors and are fixable.',
          '各项假定按后果排序：外生性决定估计是否有意义；同方差与正态只影响标准误，且可以补救。'),
      ],
      development=[
        P('Robust and cluster-robust standard errors became standard, and the emphasis in applied work shifted from fitting the model well to arguing that the comparison the coefficient represents is the intended one.',
          '稳健与聚类稳健标准误成为标准，应用研究的重心也从"把模型拟合好"转向"论证系数所代表的比较正是所要的那一个"。'),
      ],
      debates=[
        Debate('Do control variables make an estimate causal?', '加控制变量能使估计具有因果性吗？',
               [Pos('Kitchen-sink practice',
                    'Adding available controls reduces omitted variable bias, so more controls make the estimate more credible.',
                    '加入可得的控制变量能减少遗漏变量偏误，因此控制越多估计越可信。'),
                Pos('Design-based position',
                    'Controls only address confounders that are observed and correctly specified, and adding a post-treatment variable makes the estimate worse rather than better.',
                    '控制变量只能处理"被观测且设定正确"的混淆；加入处理后变量只会使估计更糟而非更好。')],
               'Settled in methods writing. The practice of reporting an increasingly saturated specification as a robustness check persists.',
               '方法学写作中已有定论。而"报告越来越饱和的设定作为稳健性检验"的做法仍在延续。'),
      ],
      theoretical=[
        P('Coefficients on control variables are not interpretable as effects. They are conditional associations from a model designed to identify one parameter, and reading them off is a common error with real consequences.',
          '控制变量的系数不能作为效应解读。它们是"为识别单一参数而设计的模型"中的条件关联，逐一解读是常见且后果真实的错误。'),
        P('Linearity is an assumption about functional form, not a neutral default, and a linear coefficient can be close to zero while a strong non-monotonic relationship exists.',
          '线性是关于函数形式的假定，而非中性的默认；即便存在很强的非单调关系，线性系数也可能接近零。'),
      ],
      empirical=[
        P('Post-treatment controls are included routinely, which blocks part of the effect being estimated and biases the coefficient in an unpredictable direction.',
          '处理后变量被例行纳入，这会阻断所估计效应的一部分，并使系数朝不可预测的方向偏倚。'),
        P('Standard errors are frequently computed as if observations were independent when they cluster by firm, school, or period, which overstates precision substantially.',
          '当观测按企业、学校或时期聚集时，标准误却常按独立观测计算，这会大幅高估精度。'),
      ],
      temporal=[
        P('Publication norms changed more than the method did. Work from before the credibility revolution routinely presented control-variable regressions as causal, and those coefficients would now require an identification strategy, so older estimates should be read as conditional associations regardless of how they were described.',
          '变化的是发表规范而非方法本身。可信性革命之前的研究常把加控制变量的回归当作因果呈现；如今这类系数需要识别策略。因此旧估计无论当时如何表述，都应作为条件关联来读。'),
        P('Sample sizes grew by orders of magnitude. With very large samples almost every coefficient is statistically significant, so significance carries little information and effect size and practical relevance carry all of it.',
          '样本量增长了几个数量级。在极大样本下几乎每个系数都统计显著，因此显著性几乎不含信息，全部信息都落在效应量与实际意义上。'),
      ],
      today=[
        P('Name the comparison the coefficient represents and defend the control set as sufficient for it. That argument, not the regression, is the contribution.',
          '应说明系数代表哪一种比较，并论证控制集对该比较而言是充分的。这一论证才是贡献，回归本身不是。'),
        P('Do not interpret control coefficients, and check that no control is measured after the treatment.',
          '不要解读控制变量的系数，并检查没有任何控制变量是在处理之后测量的。'),
      ]),

    # -------------------------------------------------------- logistic regression
    D('logistic-regression',
      era='Standard since the 1970s; the comparison problem across nested models documented from the 1990s onward.',
      era_zh='1970 年代起成为标准工具，嵌套模型间的系数比较问题自 1990 年代起被记录。',
      situation=[
        P('Many outcomes of interest are binary: adopt or not, fail or survive, leave or stay. Fitting a linear model to a binary outcome produces predictions outside zero and one and heteroskedastic errors by construction.',
          '许多关注的结果是二值的：采纳与否、失败或存续、离职或留下。对二值结果拟合线性模型会产生 0 与 1 之外的预测，且在构造上就存在异方差。'),
        P('The logit link solved the mechanical problem by modelling the log odds, which is unbounded, while keeping the predicted probability inside the valid range.',
          'Logit 联结通过对无界的对数几率建模解决了这一机械问题，同时使预测概率保持在有效区间内。'),
      ],
      argument=[
        P('The model estimates how a unit change in a regressor shifts the log odds of the outcome. Because that scale is not intuitive, results are converted to odds ratios or, better, to average marginal effects on the probability scale.',
          '模型估计的是自变量变动一个单位使结果的对数几率如何移动。由于该尺度不直观，结果会被转换为几率比，或更好地转换为概率尺度上的平均边际效应。'),
        P('The critical property is that the coefficients are identified only up to scale. The scale depends on the unexplained variance, which changes when variables are added, and this is what makes comparison across models unsafe.',
          '关键性质是：系数只在尺度意义上被识别。该尺度取决于未解释方差，而后者会随变量的加入而改变——这正是跨模型比较不安全的原因。'),
      ],
      development=[
        P('Average marginal effects became the preferred reporting form because they are comparable across models and samples in a way odds ratios are not.',
          '平均边际效应成为首选报告形式，因为它在跨模型与跨样本时具有几率比所不具备的可比性。'),
      ],
      debates=[
        Debate('Can coefficients be compared across nested models?', '嵌套模型之间的系数能比较吗？',
               [Pos('Common practice',
                    'Adding controls and observing how the focal coefficient changes is the standard way to argue that a mechanism accounts for an effect.',
                    '加入控制变量并观察焦点系数如何变化，是论证"某机制解释了效应"的标准做法。'),
                Pos('Rescaling critique',
                    'The coefficient changes partly because the scale changes when unexplained variance is reduced, so an apparent attenuation may be an artefact rather than mediation.',
                    '系数变化的部分原因是未解释方差减少导致尺度改变，因此表面上的衰减可能是假象而非中介。')],
               'The rescaling problem is established and correction methods exist; the uncorrected comparison remains common.',
               '尺度重标问题已被确立且有校正方法；未校正的比较仍很常见。'),
      ],
      theoretical=[
        P('Odds ratios are frequently read as risk ratios. When the base rate is high the two diverge substantially and the odds ratio overstates the practical difference.',
          '几率比常被读作风险比。当基础发生率较高时二者差异很大，几率比会夸大实际差别。'),
        P('The model gives a probability for an average case, and where effects are heterogeneous that probability may describe nobody in the sample.',
          '模型给出的是"平均个案"的概率；当效应异质时，该概率可能不描述样本中的任何人。'),
      ],
      empirical=[
        P('Rare outcomes produce unstable estimates and separation, and studies frequently proceed without reporting the events-per-variable ratio.',
          '罕见结果会产生不稳定估计与完全分离，而研究常常不报告"每个变量对应的事件数"就继续推进。'),
        P('Predicted probabilities are often evaluated only on discrimination such as AUC, while calibration — whether the predicted probabilities are right — goes unreported.',
          '预测概率常常只以 AUC 等区分度指标评估，而校准度——预测概率是否准确——却未被报告。'),
      ],
      temporal=[
        P('When it became standard, models were small and samples modest, so the rescaling problem was rarely consequential in practice. In current work with many covariates and large samples, nested-model comparison is a standard part of the argument and the uncorrected version is misleading more often.',
          '在它成为标准时，模型规模小、样本适中，尺度重标问题在实践中很少产生实质影响。而在当前"协变量多、样本大"的研究中，嵌套模型比较是论证的标准环节，未经校正的做法更常导致误导。'),
        P('It is now frequently used for prediction rather than explanation, where the standards are different: out-of-sample performance and calibration matter and coefficient interpretation does not, and papers often mix the two purposes.',
          '它如今常被用于预测而非解释，而两者标准不同：预测关心样本外表现与校准，不关心系数解读；论文却常把两种目的混在一起。'),
      ],
      today=[
        P('Report average marginal effects rather than raw coefficients or odds ratios, and state the base rate so the reader can judge practical magnitude.',
          '应报告平均边际效应而非原始系数或几率比，并说明基础发生率，使读者能判断实际量级。'),
        P('If comparing nested models, use a method that corrects for rescaling or say the comparison is descriptive.',
          '若要比较嵌套模型，应使用校正尺度重标的方法，或说明该比较只是描述性的。'),
      ]),

    # --------------------------------------------------------- synthetic control
    D('synthetic-control',
      era='Introduced in 2003 and formalized in 2010; now standard for single-unit policy evaluation.',
      era_zh='2003 年提出，2010 年形式化，现已成为单一单位政策评估的标准方法。',
      situation=[
        P('Difference-in-differences needs a comparison group that would have moved in parallel. When the treated unit is a single country, state, or firm, no individual comparison unit is convincing and choosing one is a judgement the reader cannot check.',
          '双重差分需要一个本会平行变动的对照组。当处理单位是单一国家、州或企业时，任何单个对照单位都不具说服力，而选择哪一个是读者无法核查的判断。'),
        P('The proposal was to stop choosing and start constructing: build a weighted combination of untreated units that reproduces the treated unit pre-treatment path, and let the data determine the weights.',
          '该方法主张不再"选择"而是"构造"：用未受处理单位的加权组合复现处理单位的处理前轨迹，并让数据决定权重。'),
      ],
      argument=[
        P('Weights are chosen so the synthetic unit matches the treated unit on pre-treatment outcomes and predictors, and are constrained to be non-negative and sum to one, which prevents extrapolation beyond the donor pool.',
          '权重的选择使合成单位在处理前的结果与预测变量上匹配处理单位，并被约束为非负且和为一，从而防止外推到供体池之外。'),
        P('The post-treatment gap between the treated unit and its synthetic counterpart is the estimate. Its credibility rests entirely on the quality of the pre-treatment fit, which the reader can see.',
          '处理后处理单位与其合成对照之间的落差即为估计值。其可信度完全取决于处理前的拟合质量，而这是读者可以看见的。'),
        P('Inference is permutation based: apply the same procedure to each untreated donor and ask how unusual the treated unit gap is relative to that distribution.',
          '推断基于置换：对每个未受处理的供体施加同样的程序，再看处理单位的落差相对于该分布有多不寻常。'),
      ],
      development=[
        P('Extensions handle multiple treated units and staggered timing, and bias-correction methods were developed for cases where the pre-treatment fit is imperfect.',
          '扩展方法可处理多个处理单位与错时处理；针对处理前拟合不完美的情形也发展出偏差校正方法。'),
      ],
      debates=[
        Debate('How good must the pre-treatment fit be?', '处理前拟合要多好才够？',
               [Pos('Strict position',
                    'Poor pre-treatment fit invalidates the design; if the synthetic unit cannot track the treated unit before the intervention there is no reason to trust it after.',
                    '处理前拟合差就使设计失效；若合成单位在干预前无法追踪处理单位，就没有理由在干预后信任它。'),
                Pos('Permissive position',
                    'Some imperfection is inevitable, and bias-correction methods can adjust for it rather than discarding the analysis.',
                    '一定程度的不完美不可避免，偏差校正方法可以加以调整，而不必放弃分析。')],
               'The strict position dominates in practice: pre-treatment RMSPE is reported and a poor fit is treated as disqualifying.',
               '实践中严格立场占主导：处理前 RMSPE 会被报告，拟合差被视为不合格。'),
      ],
      theoretical=[
        P('The estimate applies to one unit. It is a case study with a credible counterfactual, not a population effect, and it cannot be generalized without additional argument.',
          '估计只适用于一个单位。它是配有可信反事实的案例研究，而非总体效应；没有额外论证不能推广。'),
        P('The donor pool is a researcher choice, and including units affected by the same shock or by spillovers contaminates the counterfactual.',
          '供体池由研究者选定；纳入受同一冲击影响或存在溢出的单位会污染反事实。'),
      ],
      empirical=[
        P('Permutation inference has low power with a small donor pool, and a gap can fail to be unusual simply because there are few donors to compare against.',
          '供体池小时置换推断的功效很低；落差之所以"不显著异常"，可能只是因为可比较的供体太少。'),
        P('Results are sensitive to the predictor set and the pre-treatment window, and reporting one specification without sensitivity leaves the reader unable to judge.',
          '结果对预测变量集与处理前窗口敏感；只报告一种设定而不做敏感性分析，读者无从判断。'),
      ],
      temporal=[
        P('The method was designed for long annual series on aggregate units where a stable pre-period of many years exists. Where outcomes are high frequency and structural breaks are common, finding a long clean pre-period is harder and the fit that justifies the design may not be available.',
          '该方法针对的是聚合单位上的长年度序列，前提是存在长达多年的稳定处理前期。当结果为高频且结构性断点常见时，找到一段干净的长处理前期更难，而支撑设计的拟合可能并不存在。'),
        P('Early applications sometimes reported a gap without the permutation distribution, which is now considered incomplete. Those results should be read as descriptive comparisons rather than as inference.',
          '早期应用有时只报告落差而不给置换分布，如今这被视为不完整。这类结果应作为描述性比较而非推断来读。'),
      ],
      today=[
        P('Report pre-treatment fit, the donor pool and why each unit is in it, and the full permutation distribution. Those three are what make the design checkable.',
          '应报告处理前拟合、供体池及每个单位入选的理由，以及完整的置换分布。这三项使该设计可被核查。'),
        P('State plainly that the estimate is for one unit. Presenting it as a general policy effect claims more than the design supports.',
          '应直白说明估计只针对一个单位。把它呈现为普遍的政策效应，是主张超出设计所能支撑的范围。'),
      ]),

    # ---------------------------------------------------------------- embeddings
    D('embeddings',
      era='Word embeddings entered social science research around 2013; contextual and sentence embeddings displaced them from 2019.',
      era_zh='词嵌入约 2013 年进入社会科学研究，2019 年起被上下文与句子嵌入取代。',
      situation=[
        P('Text methods based on counting words could not recognize that two documents saying the same thing in different vocabulary were similar. Exact term matching was the binding limitation.',
          '基于词频统计的文本方法无法识别"用不同词汇表达同一意思"的两份文档是相似的。精确词项匹配是根本限制。'),
        P('Embeddings addressed it by representing text as dense vectors positioned so that semantically related items sit close together, which turns meaning into geometry.',
          '嵌入通过把文本表示为稠密向量、使语义相关者在空间中彼此靠近来解决这一问题，从而把意义转化为几何。'),
      ],
      argument=[
        P('The representation is learned from co-occurrence: items appearing in similar contexts get similar vectors. Similarity is then measured as distance or cosine in that space.',
          '该表示从共现中学习：出现在相似语境中的项获得相似向量。相似性随后以该空间中的距离或余弦度量。'),
        P('Nothing in this guarantees the geometry corresponds to the construct a researcher cares about. The space encodes whatever regularities were in the training corpus, including its biases and its period.',
          '这一切并不保证几何结构对应研究者所关心的构念。该空间编码的是训练语料中的任何规律，包括其偏见与其时代特征。'),
        P('Using embeddings as a measure therefore requires validation against human judgement, in the same way a dictionary or a classifier does.',
          '因此把嵌入用作测量，同样需要对照人工判断加以验证——与词典或分类器一样。'),
      ],
      development=[
        P('Static word vectors gave way to contextual models where the same word receives different vectors in different sentences, which fixed a real limitation and made version pinning essential.',
          '静态词向量让位于上下文模型：同一个词在不同句子中获得不同向量。这修正了一个真实局限，也使版本锁定变得必要。'),
      ],
      debates=[
        Debate('Does cosine similarity measure a construct?', '余弦相似度能测量构念吗？',
               [Pos('Measurement position',
                    'Validated against human similarity judgements on a sample, embedding distance is a defensible measure of semantic relatedness.',
                    '在样本上对照人工相似性判断完成验证后，嵌入距离是语义相关性的可辩护测量。'),
                Pos('Skeptical position',
                    'Similarity in the space reflects distributional regularity, which is not the same as the theoretical relation being claimed, and validation is usually skipped.',
                    '该空间中的相似性反映的是分布规律，与所主张的理论关系并非一回事，而验证通常被跳过。')],
               'The requirement for validation is increasingly accepted; the practice of using raw cosine as a construct measure remains common.',
               '"必须验证"的要求日益被接受；直接用原始余弦作为构念测量的做法仍很普遍。'),
      ],
      theoretical=[
        P('Embedding spaces encode social biases present in training data. Where the research question concerns those very dimensions, the measure and the phenomenon are entangled.',
          '嵌入空间会编码训练数据中存在的社会偏见。当研究问题恰好涉及这些维度时，测量与现象相互纠缠。'),
        P('Distance is not an interval scale with a meaningful zero, so comparisons of distance magnitudes across studies or models are not interpretable.',
          '距离不是具有实义零点的等距尺度，因此跨研究或跨模型比较距离大小是无法解读的。'),
      ],
      empirical=[
        P('Results depend on the model version and the preprocessing, and a study that does not pin both cannot be reproduced even by its own authors later.',
          '结果取决于模型版本与预处理；不锁定二者的研究，日后连作者自己也无法复现。'),
        P('Nearest-neighbour inspection is reported as validation, but it demonstrates face plausibility rather than that the measure tracks the construct across the corpus.',
          '最近邻检视常被当作验证报告，但它只表明表面合理性，而非该测量在整个语料上追踪了目标构念。'),
      ],
      temporal=[
        P('Static embeddings published before 2019 handled polysemy poorly, so measures built on them conflate distinct senses of the same word. Findings from that period should be checked before being treated as equivalent to contextual-embedding results.',
          '2019 年前发布的静态嵌入对多义词处理很差，基于它们的测量会把同一词的不同义项混同。该时期的发现在被等同于上下文嵌入的结果之前，应先加以核查。'),
        P('Models are deprecated and replaced on vendor timelines rather than research ones. A measure built on a hosted model can become unreproducible when the version is retired, which is a reproducibility risk the older count-based methods did not have.',
          '模型按厂商而非研究的时间表被弃用与替换。基于托管模型构建的测量，可能在版本下线后无法复现——这是旧的计数方法所不存在的可复现性风险。'),
      ],
      today=[
        P('Pin the model version, publish the preprocessing, and validate against human judgement on a random sample before using distances as a variable.',
          '在把距离用作变量之前，应锁定模型版本、公开预处理，并在随机样本上对照人工判断验证。'),
        P('Prefer a local model you can archive over a hosted one you cannot, where the analysis needs to be reproducible years later.',
          '当分析需要在数年后仍可复现时，应优先使用可归档的本地模型，而非无法归档的托管模型。'),
      ]),

    # ---------------------------------------------------------- text classification
    D('text-classification',
      era='Established in machine learning; adopted for social science measurement from around 2010 and transformed by language models from 2020.',
      era_zh='源自机器学习，约 2010 年起用于社会科学测量，2020 年后因语言模型而改观。',
      situation=[
        P('Content analysis produces valid measures but does not scale: hand coding a million documents is not feasible, and sampling down to what can be coded discards the coverage that made the corpus valuable.',
          '内容分析产生有效测量却无法规模化：人工编码一百万份文档不可行，而抽样到可编码的规模又丢弃了使该语料有价值的覆盖面。'),
        P('Supervised classification offered a way to keep the codebook and the validity argument while extending coverage: code a sample by hand, train on it, and apply to the rest.',
          '监督分类提供了一条路径：保留编码手册与效度论证的同时扩大覆盖——手工编码一个样本、据此训练、再应用于其余部分。'),
      ],
      argument=[
        P('The categories come from theory and a codebook, not from the data. That is what distinguishes it from topic modelling and what makes the output interpretable as a measure of a defined construct.',
          '类别来自理论与编码手册，而非数据。这既是它区别于主题模型之处，也是其输出能作为"既定构念的测量"被解读的原因。'),
        P('Validity rests on two things: the training labels must be reliable, and held-out performance must be reported per class rather than as overall accuracy, since imbalance makes overall accuracy uninformative.',
          '效度取决于两点：训练标签必须可靠；留出集表现必须分类别报告而非只报总体准确率——因为类别不平衡会使总体准确率毫无信息量。'),
        P('Classification error propagates. Feeding predicted labels into a downstream regression without accounting for misclassification biases the estimates, usually toward zero.',
          '分类误差会传播。把预测标签直接放进下游回归而不处理误分类，会使估计有偏，通常偏向零。'),
      ],
      development=[
        P('Fine-tuned language models and zero-shot classification reduced the labelled data needed, which lowered the cost of the method while leaving the validation requirement unchanged.',
          '微调语言模型与零样本分类降低了对标注数据的需求，从而降低了方法成本，而验证要求并未改变。'),
      ],
      debates=[
        Debate('Can a language model replace human coders?', '语言模型能取代人工编码者吗？',
               [Pos('Substitution position',
                    'Modern models match or exceed trained coder agreement on many tasks at a fraction of the cost.',
                    '在许多任务上，现代模型的一致性已达到或超过受训编码者，而成本只是零头。'),
                Pos('Validation position',
                    'Agreement varies sharply by task and by subgroup, and a model that matches humans overall can fail systematically on the cases a study is about.',
                    '一致性随任务与子群体大幅变化；总体上与人相当的模型，可能在研究真正关心的那些个案上系统性失败。')],
               'Open. The practical consensus is that models can code but the validation sample cannot be skipped.',
               '未决。实践共识是：模型可以编码，但验证样本不能省略。'),
      ],
      theoretical=[
        P('The classifier learns what distinguishes the training labels, which may be a spurious correlate rather than the construct. High accuracy is consistent with the model using the wrong signal.',
          '分类器学到的是"区分训练标签的东西"，那可能是虚假相关而非构念本身。高准确率与"模型用错信号"完全可以并存。'),
        P('Categories fixed in advance cannot capture what the codebook did not anticipate, which is the cost of the validity the method buys.',
          '事先固定的类别无法捕捉编码手册未曾预料之物——这是该方法换取效度所付的代价。'),
      ],
      empirical=[
        P('Tuning on the test set is common and produces reported performance that will not hold on new data.',
          '在测试集上调参很常见，由此报告的表现在新数据上不会成立。'),
        P('Per-subgroup performance is rarely reported, so a classifier that works well overall and poorly for a subpopulation looks acceptable.',
          '分子群体的表现很少被报告，因此"总体良好、对某一子群体很差"的分类器看起来是可接受的。'),
      ],
      temporal=[
        P('The cost structure inverted. When labelling was the bottleneck, studies used small training sets and simple models; now labelling is cheap and the bottleneck is validation, which has not become cheaper and is more often skipped.',
          '成本结构发生了反转。当标注是瓶颈时，研究使用小训练集与简单模型；如今标注变得廉价，瓶颈转为验证——而验证并未变便宜，反而更常被跳过。'),
        P('Model-coded variables built on hosted models inherit the version problem: a measure produced by one model version may not be reproducible after it is retired, so the coding decisions need to be archived rather than the API call.',
          '基于托管模型的"模型编码变量"继承了版本问题：某一版本产生的测量在下线后可能无法复现，因此需要归档的是编码决策而非 API 调用。'),
      ],
      today=[
        P('Report per-class and per-subgroup held-out performance, and hand-code a validation sample even when a model does the bulk coding.',
          '应分类别、分子群体报告留出集表现；即便主体编码由模型完成，也要人工编码一个验证样本。'),
        P('If predicted labels feed a regression, account for classification error or state that the estimate is attenuated by an unknown amount.',
          '若预测标签进入回归，应处理分类误差，或声明估计被未知幅度地衰减。'),
      ]),

    # --------------------------------------------------------------- ethnography
    D('ethnography',
      era='Established in anthropology in the early 20th century; adapted to organizations from the 1970s and to digital settings from the 2000s.',
      era_zh='20 世纪初在人类学中确立，1970 年代起用于组织研究，2000 年代起延伸至数字情境。',
      situation=[
        P('Interviews collect accounts, and accounts are shaped by what people can articulate and are willing to say. Much of what governs work is tacit, routine, and invisible to the people doing it.',
          '访谈收集的是叙述，而叙述受限于人们能表达什么、愿意说什么。而支配工作的许多东西是默会的、例行的，对身处其中的人不可见。'),
        P('Sustained presence was the answer: observe what people actually do over enough time that the routine becomes visible and the researcher stops being an event.',
          '答案是长期在场：观察人们实际做什么，时间长到例行之事变得可见、研究者本身不再构成一个事件。'),
      ],
      argument=[
        P('The method is prolonged participation combined with systematic recording. Field notes separate description from interpretation so that a later reading can distinguish what was seen from what it was taken to mean.',
          '该方法是长期参与与系统记录的结合。田野笔记把描述与解读分开，使日后重读时能区分"看到了什么"与"被理解为什么"。'),
        P('Positionality is part of the method rather than a confession. Who the researcher is determines what they are shown, and an account that does not address it has omitted a determinant of the data.',
          '立场性是方法的一部分，而非一种坦白。研究者是谁决定了他们被展示什么；不处理这一点的研究，遗漏了数据的一项决定因素。'),
        P('Analysis runs during fieldwork, not after. What is noticed early directs where to look next, which is why the method cannot be reduced to a data collection phase followed by a coding phase.',
          '分析在田野过程中进行，而非事后。早期注意到的东西决定接下来看哪里——这正是该方法无法被化约为"先收集、后编码"两阶段的原因。'),
      ],
      development=[
        P('Digital and multi-sited variants extended it to settings with no single physical location, where the field is constituted by following a practice, a platform, or an object across sites.',
          '数字与多点变体把它扩展到没有单一物理场所的情境：田野由"跟随某种实践、某个平台或某个对象跨场所移动"来构成。'),
      ],
      debates=[
        Debate('Can ethnography be done remotely?', '民族志可以远程进行吗？',
               [Pos('Digital position',
                    'Practice increasingly happens in logged, observable digital spaces, and following it there is continuous with following it physically.',
                    '实践日益发生在有记录、可观察的数字空间中；在那里跟随它，与在物理空间跟随是连续的。'),
                Pos('Presence position',
                    'Co-presence gives access to the unspoken, the atmospheric, and the things people do not put in writing, which is precisely what the method exists to reach.',
                    '共同在场使人得以接触未言明的、氛围性的、以及人们不会写下来的东西——而这恰恰是该方法存在的理由。')],
               'Open, and the honest position is that they access different things and should not be presented as equivalent.',
               '未决；诚实的立场是：二者接触到的是不同的东西，不应被呈现为等同。'),
      ],
      theoretical=[
        P('The researcher presence changes the setting. That is not a flaw to be minimized away but a condition to be reported, and an account claiming no influence is less credible rather than more.',
          '研究者的在场会改变场域。这不是应被"最小化掉"的缺陷，而是应被报告的条件；声称毫无影响的叙述不是更可信，而是更不可信。'),
        P('Generalization is to theory, not population. A claim that a mechanism operates elsewhere requires an argument about why the conditions transfer.',
          '推广的对象是理论而非总体。主张某机制在别处也起作用，需要论证条件为何可迁移。'),
      ],
      empirical=[
        P('Access is granted by organizations with something to gain and is withdrawn when findings become uncomfortable, which shapes both which settings are studied and what is published.',
          '进入许可由"有所图"的组织授予，并在发现变得不便时被撤回，这既塑造了哪些场域被研究，也塑造了什么被发表。'),
        P('Field notes are the data and are almost never available for scrutiny, so the reader evaluates the analysis on the basis of the account alone.',
          '田野笔记就是数据，却几乎从不可供检视，因此读者只能依据叙述本身来评估分析。'),
      ],
      temporal=[
        P('The method assumed the researcher could be present where the work happens. Distributed work has no such place, and a study that observes a video call and a message channel is observing the recorded surface of the work rather than the work.',
          '该方法假定研究者能在工作发生之处在场。分布式工作没有这样一个"处所"；观察视频会议与消息频道的研究，观察的是工作被记录下来的表层，而非工作本身。'),
        P('Ethical review and data protection now constrain what can be recorded, especially where digital traces include third parties who never consented. Studies from before those constraints had access to material that would not be collectable now.',
          '伦理审查与数据保护如今限制了可记录的内容，尤其当数字痕迹涉及从未同意的第三方时。此类约束之前的研究，接触到的材料如今已无法采集。'),
      ],
      today=[
        P('State the access arrangement, the duration, the observation coverage across situations, and positionality. These are what allow a reader to judge what the account could and could not have seen.',
          '应说明进入安排、持续时间、跨情境的观察覆盖以及研究者立场。正是这些让读者判断该叙述可能看到什么、不可能看到什么。'),
        P('If the fieldwork was remote, say what was not observable rather than presenting it as equivalent to co-presence.',
          '若田野是远程进行的，应说明什么无法被观察，而不是把它呈现为与共同在场等同。'),
      ]),
])
