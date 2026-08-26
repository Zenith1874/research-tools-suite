# -*- coding: utf-8 -*-
"""Method entries for the research catalog.

Split out of ``build_research_catalog.py`` only for file size; edit here and
re-run that script to regenerate ``data/research_catalog.json``.
"""

METHODS = [{'id': 'ols-regression',
  'name': 'OLS Regression',
  'category': 'quantitative',
  'sub_category': 'Regression',
  'difficulty': 'Introductory',
  'description': 'Estimates conditional means of a continuous outcome as a linear function of '
                 'covariates.',
  'tags': ['regression', 'regression analysis', 'linear regression', 'ordinary least squares'],
  'broad_tags': [],
  'use_when': ['The outcome is continuous and roughly unbounded in the observed range.',
               'The question is descriptive or predictive, or identification comes from the design '
               'rather than the estimator.'],
  'assumptions': ['Linearity in parameters',
                  'No perfect collinearity',
                  'Exogeneity of regressors conditional on controls',
                  'Homoskedastic or correctly adjusted errors'],
  'workflow': ['Specify the estimand and the comparison you want the coefficient to represent.',
               'Inspect univariate distributions and missingness before modelling.',
               'Fit the baseline specification with pre-registered controls.',
               'Recompute standard errors at the level where treatment or sampling varies.',
               'Report specification sensitivity rather than a single preferred model.'],
  'diagnostics': ['Residual plots',
                  'Variance inflation factors',
                  'Influence and leverage diagnostics',
                  'Heteroskedasticity-robust errors'],
  'pitfalls': ['Interpreting a control-variable coefficient causally when only the focal variable '
               'was designed for identification.',
               'Adding post-treatment variables as controls, which blocks part of the effect being '
               'estimated.',
               'Reporting default standard errors when observations cluster within groups.'],
  'related_methods': ['logistic-regression', 'fixed-effects', 'panel-data', 'moderation'],
  'code_examples': [{'language': 'R',
                     'title': 'R sketch',
                     'code': 'fit <- lm(outcome ~ treatment + x1 + x2, data = df)\n'
                             'summary(fit)\n'
                             '\n'
                             'library(sandwich); library(lmtest)\n'
                             'coeftest(fit, vcov = vcovCL, cluster = ~ firm_id)'},
                    {'language': 'Python',
                     'title': 'Python sketch',
                     'code': 'import statsmodels.formula.api as smf\n'
                             '\n'
                             'fit = smf.ols("outcome ~ treatment + x1 + x2", data=df).fit(\n'
                             '    cov_type="cluster", cov_kwds={"groups": df["firm_id"]}\n'
                             ')\n'
                             'print(fit.summary())'},
                    {'language': 'Stata',
                     'title': 'Stata sketch',
                     'code': 'regress outcome treatment x1 x2, vce(cluster firm_id)\n'
                             'estimates store baseline'}],
  'source_status': 'curated_scaffold',
  'name_zh': '普通最小二乘回归',
  'description_zh': '将连续因变量的条件均值估计为自变量的线性函数。',
  'seminal_works': []},
 {'id': 'logistic-regression',
  'name': 'Logistic Regression',
  'category': 'quantitative',
  'sub_category': 'Regression',
  'difficulty': 'Introductory',
  'description': 'Models the probability of a binary outcome through a logit link.',
  'tags': ['logistic regression'],
  'broad_tags': [],
  'use_when': ['The outcome is binary (adopt / not adopt, stay / leave).',
               'You want predicted probabilities or odds ratios rather than a linear probability '
               'slope.'],
  'assumptions': ['Independent observations conditional on covariates',
                  'Correct link specification',
                  'No complete separation',
                  'Adequate events per predictor'],
  'workflow': ['State whether the target is a probability, an odds ratio, or a marginal effect.',
               'Check the event rate and events-per-variable ratio.',
               'Fit the model and convert coefficients to average marginal effects for '
               'interpretation.',
               'Assess calibration and discrimination separately.'],
  'diagnostics': ['Hosmer–Lemeshow or calibration plots',
                  'ROC / AUC',
                  'Separation checks',
                  'Influence statistics'],
  'pitfalls': ['Comparing raw coefficients across nested logit models, where scaling differs by '
               'specification.',
               'Reading odds ratios as risk ratios when the base rate is high.',
               'Ignoring class imbalance when the model is used for prediction.'],
  'related_methods': ['ols-regression', 'fixed-effects', 'experiment'],
  'code_examples': [{'language': 'R',
                     'title': 'R sketch',
                     'code': 'fit <- glm(adopt ~ treatment + x1, data = df, family = binomial())\n'
                             'summary(fit)\n'
                             '\n'
                             'library(margins)\n'
                             'summary(margins(fit))'},
                    {'language': 'Python',
                     'title': 'Python sketch',
                     'code': 'import statsmodels.formula.api as smf\n'
                             '\n'
                             'fit = smf.logit("adopt ~ treatment + x1", data=df).fit()\n'
                             'print(fit.get_margeff(at="overall").summary())'},
                    {'language': 'Stata',
                     'title': 'Stata sketch',
                     'code': 'logit adopt treatment x1, vce(robust)\nmargins, dydx(*)'}],
  'source_status': 'curated_scaffold',
  'name_zh': '逻辑回归',
  'description_zh': '通过 logit 联结函数对二值结果的发生概率建模。',
  'seminal_works': []},
 {'id': 'panel-data',
  'name': 'Panel Data Analysis',
  'category': 'quantitative',
  'sub_category': 'Panel',
  'difficulty': 'Intermediate',
  'description': 'Uses repeated observations of the same units over time to separate within-unit '
                 'from between-unit variation.',
  'tags': ['panel_data', 'panel data', 'panel data analysis', 'panel analysis', 'dynamic panel'],
  'broad_tags': [],
  'use_when': ['The same units are observed in multiple periods.',
               'You want to control for stable unobserved unit characteristics.'],
  'assumptions': ['Units are observed consistently enough that attrition is not outcome-related.',
                  'The specification matches how the effect is assumed to vary over time.'],
  'workflow': ['Describe the panel structure: units, periods, balance, and attrition.',
               'Decide whether the estimand is a within-unit or between-unit comparison.',
               'Choose the estimator that matches that estimand.',
               'Cluster inference at the unit level.',
               'Report how results change under alternative panel windows.'],
  'diagnostics': ['Balance and attrition tables',
                  'Within vs between variance decomposition',
                  'Serial correlation tests'],
  'pitfalls': ['Treating unbalanced attrition as random when leavers differ systematically.',
               'Reporting pooled OLS results as if they controlled for unit heterogeneity.'],
  'related_methods': ['fixed-effects',
                      'random-effects',
                      'difference-in-differences',
                      'multilevel-modeling'],
  'code_examples': [{'language': 'R',
                     'title': 'R sketch',
                     'code': 'library(plm)\n'
                             'pdf <- pdata.frame(df, index = c("firm_id", "year"))\n'
                             'fit <- plm(y ~ x1 + x2, data = pdf, model = "within")\n'
                             'summary(fit)'},
                    {'language': 'Python',
                     'title': 'Python sketch',
                     'code': 'from linearmodels.panel import PanelOLS\n'
                             '\n'
                             'panel = df.set_index(["firm_id", "year"])\n'
                             'fit = PanelOLS.from_formula("y ~ x1 + x2 + EntityEffects", '
                             'panel).fit(\n'
                             '    cov_type="clustered", cluster_entity=True\n'
                             ')\n'
                             'print(fit)'},
                    {'language': 'Stata',
                     'title': 'Stata sketch',
                     'code': 'xtset firm_id year\n'
                             'xtdescribe\n'
                             'xtreg y x1 x2, fe vce(cluster firm_id)'}],
  'source_status': 'curated_scaffold',
  'name_zh': '面板数据分析',
  'description_zh': '利用同一批个体在多个时点的重复观测，区分个体内变异与个体间变异。',
  'seminal_works': []},
 {'id': 'fixed-effects',
  'name': 'Fixed Effects',
  'category': 'quantitative',
  'sub_category': 'Panel',
  'difficulty': 'Intermediate',
  'description': 'Absorbs time-invariant unit characteristics so identification comes from '
                 'within-unit change.',
  'tags': ['fixed-effects',
           'fixed-effects regression',
           'two-way fixed-effects models',
           'fixed-effects panel model',
           'high-dimensional fixed-effects panel regression'],
  'broad_tags': ['panel_data'],
  'use_when': ['Unobserved stable confounders differ across units.',
               'The focal variable actually changes within units over time.'],
  'assumptions': ['Time-invariant confounders are additive and absorbed by the unit effect.',
                  'No time-varying confounder correlated with the regressor remains.',
                  'Sufficient within-unit variation exists to identify the coefficient.'],
  'workflow': ['Confirm the focal variable varies within units, not only across them.',
               'Choose unit, time, or two-way effects and justify the choice.',
               'Estimate the model and absorb the effects explicitly.',
               'Cluster standard errors at the level of treatment assignment.',
               'Compare within-estimates to pooled estimates and explain differences.'],
  'diagnostics': ['Within-variation share for the focal regressor',
                  'Two-way vs one-way comparison',
                  'Cluster-robust inference checks'],
  'pitfalls': ['Using fixed effects when the regressor barely varies within units, which inflates '
               'standard errors and amplifies measurement error.',
               'Treating two-way fixed effects with staggered treatment timing as a valid average '
               'treatment effect.',
               'Interpreting absorbed time-invariant characteristics as having been shown to not '
               'matter.'],
  'related_methods': ['panel-data', 'random-effects', 'difference-in-differences', 'event-study'],
  'code_examples': [{'language': 'R',
                     'title': 'R sketch',
                     'code': 'library(fixest)\n'
                             'fit <- feols(y ~ x1 | firm_id + year, data = df, cluster = ~ '
                             'firm_id)\n'
                             'summary(fit)'},
                    {'language': 'Python',
                     'title': 'Python sketch',
                     'code': 'import pyfixest as pf\n'
                             '\n'
                             'fit = pf.feols("y ~ x1 | firm_id + year", data=df, vcov={"CRV1": '
                             '"firm_id"})\n'
                             'fit.summary()'},
                    {'language': 'Stata',
                     'title': 'Stata sketch',
                     'code': 'xtset firm_id year\n'
                             'reghdfe y x1, absorb(firm_id year) vce(cluster firm_id)'}],
  'source_status': 'curated_scaffold',
  'name_zh': '固定效应',
  'description_zh': '吸收不随时间变化的个体特征，使识别只来自个体内部的变化。',
  'seminal_works': []},
 {'id': 'random-effects',
  'name': 'Random Effects',
  'category': 'quantitative',
  'sub_category': 'Panel',
  'difficulty': 'Intermediate',
  'description': 'Models unit heterogeneity as a random draw, allowing both within- and '
                 'between-unit variation to inform the estimate.',
  'tags': ['random effects', 'random-effects model'],
  'broad_tags': ['panel_data'],
  'use_when': ['You need to estimate the effect of a time-invariant characteristic.',
               'Unit effects are plausibly uncorrelated with the regressors.'],
  'assumptions': ['Unit effects are uncorrelated with the covariates',
                  'Correctly specified variance components',
                  'Random sampling of units from a population'],
  'workflow': ['State why between-unit variation should contribute to the estimate.',
               'Fit both random- and fixed-effects specifications.',
               'Test the orthogonality assumption.',
               'Report both estimates when the test is inconclusive.'],
  'diagnostics': ['Hausman test',
                  'Between vs within estimate comparison',
                  'Variance component estimates'],
  'pitfalls': ['Choosing random effects because the Hausman test failed to reject, treating '
               'non-rejection as proof of the assumption.',
               'Using random effects purely to keep a time-invariant regressor in the model '
               'despite obvious correlation with the unit effect.'],
  'related_methods': ['fixed-effects', 'panel-data', 'multilevel-modeling'],
  'code_examples': [{'language': 'R',
                     'title': 'R sketch',
                     'code': 'library(plm)\n'
                             're <- plm(y ~ x1 + x2, data = pdf, model = "random")\n'
                             'fe <- plm(y ~ x1 + x2, data = pdf, model = "within")\n'
                             'phtest(fe, re)'},
                    {'language': 'Python',
                     'title': 'Python sketch',
                     'code': 'from linearmodels.panel import RandomEffects\n'
                             '\n'
                             'fit = RandomEffects.from_formula("y ~ 1 + x1 + x2", panel).fit()\n'
                             'print(fit)'},
                    {'language': 'Stata',
                     'title': 'Stata sketch',
                     'code': 'xtreg y x1 x2, re\n'
                             'estimates store re\n'
                             'xtreg y x1 x2, fe\n'
                             'hausman . re'}],
  'source_status': 'curated_scaffold',
  'name_zh': '随机效应',
  'description_zh': '将个体异质性建模为随机抽取，使个体内与个体间变异共同贡献于估计。',
  'seminal_works': []},
 {'id': 'difference-in-differences',
  'name': 'Difference-in-Differences',
  'category': 'quantitative',
  'sub_category': 'Causal Inference',
  'difficulty': 'Intermediate',
  'description': 'Compares the before/after change in a treated group with the contemporaneous '
                 'change in an untreated comparison group.',
  'tags': ['difference_in_differences', 'difference-in-differences'],
  'broad_tags': ['causal_inference'],
  'use_when': ['A policy, event, or rollout affected some units and not others.',
               'Outcomes are observed both before and after the intervention.',
               'The intervention timing is plausibly exogenous to the outcome path.'],
  'assumptions': ['Parallel trends absent treatment',
                  'No anticipation before the intervention',
                  'No spillover from treated to control units',
                  'Stable group composition across periods'],
  'workflow': ['Define treatment and control groups from the assignment mechanism, not from the '
               'outcome.',
               'Fix the intervention date and the estimation window before looking at outcomes.',
               'Plot raw outcome trends for both groups across all available pre-periods.',
               'Estimate the baseline two-group two-period specification.',
               'Estimate an event-study specification with leads and lags.',
               'If adoption is staggered, use an estimator robust to heterogeneous timing.',
               'Run placebo and alternative-control robustness checks.'],
  'diagnostics': ['Pre-trend test on leads',
                  'Event-study plot',
                  'Placebo intervention dates',
                  'Alternative control groups',
                  'Alternative time windows'],
  'pitfalls': ['Skipping the pre-trend inspection and reporting only the post-period difference.',
               'Controlling for variables measured after the intervention.',
               'Choosing a comparison group because it produces the expected result.',
               'Applying simple two-way fixed effects to staggered adoption, where already-treated '
               'units act as controls and can flip the sign.'],
  'related_methods': ['fixed-effects',
                      'event-study',
                      'synthetic-control',
                      'regression-discontinuity',
                      'instrumental-variables'],
  'code_examples': [{'language': 'R',
                     'title': 'R sketch',
                     'code': 'library(fixest)\n'
                             '\n'
                             '# Baseline\n'
                             'fit <- feols(y ~ treated * post | unit + period, data = df, cluster '
                             '= ~ unit)\n'
                             '\n'
                             '# Event study\n'
                             'es <- feols(y ~ i(rel_time, treated, ref = -1) | unit + period,\n'
                             '            data = df, cluster = ~ unit)\n'
                             'iplot(es)'},
                    {'language': 'Python',
                     'title': 'Python sketch',
                     'code': 'import pyfixest as pf\n'
                             '\n'
                             'baseline = pf.feols("y ~ treated:post | unit + period", data=df,\n'
                             '                    vcov={"CRV1": "unit"})\n'
                             '\n'
                             'event = pf.feols("y ~ i(rel_time, treated, ref=-1) | unit + '
                             'period",\n'
                             '                 data=df, vcov={"CRV1": "unit"})\n'
                             'event.iplot()'},
                    {'language': 'Stata',
                     'title': 'Stata sketch',
                     'code': '* Baseline\n'
                             'reghdfe y c.treated#c.post, absorb(unit period) vce(cluster unit)\n'
                             '\n'
                             '* Event study\n'
                             'reghdfe y ib(-1).rel_time#c.treated, absorb(unit period) vce(cluster '
                             'unit)\n'
                             'coefplot, vertical yline(0)'}],
  'source_status': 'curated_scaffold',
  'design_diagram': {'kind': 'did',
                     'note': 'Schematic of the comparison the estimator makes. It is not evidence '
                             'that the assumption holds in a given dataset.',
                     'series': [{'label': 'Treatment group', 'emphasis': True},
                                {'label': 'Control group', 'emphasis': False}],
                     'axis': ['Before', 'Intervention', 'After']},
  'name_zh': '双重差分',
  'description_zh': '将处理组前后变化与同期对照组的变化相比较。',
  'seminal_works': []},
 {'id': 'instrumental-variables',
  'name': 'Instrumental Variables',
  'category': 'quantitative',
  'sub_category': 'Causal Inference',
  'difficulty': 'Advanced',
  'description': 'Uses variation from an instrument that affects the outcome only through the '
                 'endogenous regressor.',
  'tags': ['instrumental variables',
           'instrumental_variables',
           'iv estimation',
           'two-stage least squares'],
  'broad_tags': ['causal_inference'],
  'use_when': ['The focal regressor is endogenous through simultaneity, omitted variables, or '
               'measurement error.',
               'A credible source of exogenous variation in that regressor exists.'],
  'assumptions': ['Relevance: the instrument predicts the endogenous regressor',
                  'Exclusion: the instrument affects the outcome only through that regressor',
                  'Independence: the instrument is as good as randomly assigned',
                  'Monotonicity, when interpreting a local average treatment effect'],
  'workflow': ['Argue the exclusion restriction substantively before running anything.',
               'Report the first stage and its strength.',
               'Estimate the two-stage model with correct standard errors.',
               'State which subpopulation the estimate applies to.',
               'Probe sensitivity to small exclusion violations.'],
  'diagnostics': ['First-stage F statistic',
                  'Weak-instrument robust confidence sets',
                  'Overidentification tests when multiple instruments exist',
                  'Reduced-form estimates'],
  'pitfalls': ['Defending the exclusion restriction with a statistical test rather than an '
               'argument; it is not testable in the just-identified case.',
               'Reporting a strong first stage as if it established exclusion.',
               'Generalising a local average treatment effect to the whole population.'],
  'related_methods': ['difference-in-differences', 'regression-discontinuity', 'fixed-effects'],
  'code_examples': [{'language': 'R',
                     'title': 'R sketch',
                     'code': 'library(fixest)\n'
                             'fit <- feols(y ~ x_exog | firm_id | x_endog ~ z, data = df)\n'
                             'summary(fit, stage = 1:2)'},
                    {'language': 'Python',
                     'title': 'Python sketch',
                     'code': 'from linearmodels.iv import IV2SLS\n'
                             '\n'
                             'fit = IV2SLS.from_formula(\n'
                             '    "y ~ 1 + x_exog + [x_endog ~ z]", data=df\n'
                             ').fit(cov_type="clustered", clusters=df["firm_id"])\n'
                             'print(fit)\n'
                             'print(fit.first_stage)'},
                    {'language': 'Stata',
                     'title': 'Stata sketch',
                     'code': 'ivregress 2sls y x_exog (x_endog = z), vce(cluster firm_id)\n'
                             'estat firststage\n'
                             'estat endogenous'}],
  'source_status': 'curated_scaffold',
  'name_zh': '工具变量',
  'description_zh': '借助只通过内生变量影响结果的工具变量获取外生变异。',
  'seminal_works': []},
 {'id': 'regression-discontinuity',
  'name': 'Regression Discontinuity',
  'category': 'quantitative',
  'sub_category': 'Causal Inference',
  'difficulty': 'Advanced',
  'description': 'Compares units just above and just below a threshold that determines treatment '
                 'assignment.',
  'tags': ['regression discontinuity', 'regression_discontinuity'],
  'broad_tags': ['causal_inference'],
  'use_when': ['Treatment is assigned by a cutoff on a continuous running variable.',
               'Units cannot precisely control which side of the cutoff they land on.'],
  'assumptions': ['Continuity of potential outcomes at the cutoff',
                  'No precise manipulation of the running variable',
                  'No other policy changing at the same threshold'],
  'workflow': ['Document the assignment rule and the exact cutoff.',
               'Plot the outcome against the running variable with a visible discontinuity check.',
               'Choose bandwidth and polynomial order using a stated data-driven rule.',
               'Estimate the local effect at the cutoff.',
               'Test density continuity and covariate balance at the threshold.'],
  'diagnostics': ['McCrary / density test',
                  'Covariate balance at the cutoff',
                  'Bandwidth sensitivity',
                  'Placebo cutoffs',
                  'Donut-hole specification'],
  'pitfalls': ['Fitting high-order global polynomials, which are driven by observations far from '
               'the cutoff.',
               'Reporting one bandwidth without sensitivity analysis.',
               'Extrapolating the local estimate to units far from the threshold.'],
  'related_methods': ['instrumental-variables', 'difference-in-differences', 'event-study'],
  'code_examples': [{'language': 'R',
                     'title': 'R sketch',
                     'code': 'library(rdrobust)\n'
                             'out <- rdrobust(y = df$y, x = df$running, c = 0)\n'
                             'summary(out)\n'
                             'rdplot(y = df$y, x = df$running, c = 0)\n'
                             'rddensity::rddensity(df$running, c = 0)'},
                    {'language': 'Python',
                     'title': 'Python sketch',
                     'code': 'from rdrobust import rdrobust, rdplot, rddensity\n'
                             '\n'
                             'out = rdrobust(y=df["y"], x=df["running"], c=0)\n'
                             'print(out)\n'
                             'rdplot(y=df["y"], x=df["running"], c=0)\n'
                             'print(rddensity(df["running"], c=0))'},
                    {'language': 'Stata',
                     'title': 'Stata sketch',
                     'code': 'rdrobust y running, c(0)\n'
                             'rdplot y running, c(0)\n'
                             'rddensity running, c(0)'}],
  'source_status': 'curated_scaffold',
  'name_zh': '断点回归',
  'description_zh': '比较决定处理分配的阈值两侧刚好相邻的个体。',
  'seminal_works': []},
 {'id': 'event-study',
  'name': 'Event Study',
  'category': 'quantitative',
  'sub_category': 'Causal Inference',
  'difficulty': 'Intermediate',
  'description': 'Traces outcome dynamics in periods relative to an event to show timing and '
                 'persistence.',
  'tags': ['event_study', 'event study', 'regulatory event study'],
  'broad_tags': ['causal_inference'],
  'use_when': ['You need to show when an effect starts, not only that it exists.',
               'You want to inspect pre-event behaviour as a check on the identifying assumption.'],
  'assumptions': ['Event timing is exogenous to the outcome path',
                  'No confounding event in the same window',
                  'A well-defined and consistently applied reference period'],
  'workflow': ['Define event time relative to a fixed reference period.',
               'Decide and disclose the estimation window.',
               'Estimate coefficients for each lead and lag.',
               'Plot coefficients with confidence intervals.',
               'Interpret pre-event coefficients as a diagnostic, not as an effect.'],
  'diagnostics': ['Joint test of pre-event coefficients',
                  'Window-length sensitivity',
                  'Alternative reference period',
                  'Placebo event dates'],
  'pitfalls': ['Reading a statistically insignificant pre-trend as proof of parallel trends when '
               'the estimates are simply imprecise.',
               'Dropping or binning leads until the pre-trend disappears.',
               'Omitting the reference period from the plot, which hides the normalization.'],
  'related_methods': ['difference-in-differences',
                      'fixed-effects',
                      'synthetic-control',
                      'regression-discontinuity'],
  'code_examples': [{'language': 'R',
                     'title': 'R sketch',
                     'code': 'library(fixest)\n'
                             'es <- feols(y ~ i(rel_time, treated, ref = -1) | unit + period,\n'
                             '            data = df, cluster = ~ unit)\n'
                             'iplot(es, ref.line = TRUE)\n'
                             'wald(es, "rel_time::-[2-9]")'},
                    {'language': 'Python',
                     'title': 'Python sketch',
                     'code': 'import pyfixest as pf\n'
                             '\n'
                             'es = pf.feols("y ~ i(rel_time, treated, ref=-1) | unit + period",\n'
                             '              data=df, vcov={"CRV1": "unit"})\n'
                             'es.iplot()'},
                    {'language': 'Stata',
                     'title': 'Stata sketch',
                     'code': 'reghdfe y ib(-1).rel_time#c.treated, absorb(unit period) vce(cluster '
                             'unit)\n'
                             'coefplot, vertical yline(0) xline(0)\n'
                             'testparm i(-6/-2).rel_time#c.treated'}],
  'source_status': 'curated_scaffold',
  'name_zh': '事件研究法',
  'description_zh': '以相对事件时间刻画结果的动态，展示效应何时出现、能否持续。',
  'seminal_works': []},
 {'id': 'synthetic-control',
  'name': 'Synthetic Control',
  'category': 'quantitative',
  'sub_category': 'Causal Inference',
  'difficulty': 'Advanced',
  'description': 'Builds a weighted combination of untreated units that tracks the treated unit '
                 'before the intervention.',
  'tags': ['synthetic control', 'synthetic control method', 'synthetic control methods'],
  'broad_tags': ['causal_inference'],
  'use_when': ['One or a few treated units, such as a country, state, or firm.',
               'A long pre-intervention series and a pool of comparable untreated units.'],
  'assumptions': ['The pre-period fit is good and achieved without extrapolation',
                  'No untreated donor is affected by the intervention',
                  'No other shock hits the treated unit at the same time'],
  'workflow': ['Assemble a donor pool of plausibly unaffected units.',
               'Choose predictors and the pre-period matching window in advance.',
               'Fit the weights and report pre-period fit quality.',
               'Compare observed and synthetic post-period paths.',
               'Run placebo tests across donors and across time.'],
  'diagnostics': ['Pre-period RMSPE',
                  'In-space placebo distribution',
                  'In-time placebo intervention',
                  'Leave-one-donor-out stability'],
  'pitfalls': ['Reporting a gap without the placebo distribution, so the result has no reference '
               'for how unusual it is.',
               'Accepting poor pre-period fit and interpreting the post-period gap anyway.',
               'Including donors that were themselves affected by the intervention.'],
  'related_methods': ['difference-in-differences', 'event-study', 'fixed-effects'],
  'code_examples': [{'language': 'R',
                     'title': 'R sketch',
                     'code': 'library(Synth)\n'
                             'prep <- dataprep(foo = df, predictors = c("x1", "x2"),\n'
                             '                 dependent = "y", unit.variable = "unit_id",\n'
                             '                 time.variable = "year", treatment.identifier = 7,\n'
                             '                 controls.identifier = setdiff(unique(df$unit_id), '
                             '7),\n'
                             '                 time.optimize.ssr = 2000:2010, time.plot = '
                             '2000:2016)\n'
                             'out <- synth(prep)\n'
                             'path.plot(out$solution.w, prep)'},
                    {'language': 'Python',
                     'title': 'Python sketch',
                     'code': 'from SyntheticControlMethods import Synth\n'
                             '\n'
                             'sc = Synth(df, outcome="y", id="unit", time="year",\n'
                             '           treated_unit="Region A", treatment_period=2011)\n'
                             'sc.plot(["original", "pointwise", "in-space placebo"])'},
                    {'language': 'Stata',
                     'title': 'Stata sketch',
                     'code': 'synth y x1 x2, trunit(7) trperiod(2011) fig\n'
                             'synth_runner y x1 x2, trunit(7) trperiod(2011)'}],
  'source_status': 'curated_scaffold',
  'name_zh': '合成控制法',
  'description_zh': '用未受处理单位的加权组合拟合处理单位的处理前轨迹。',
  'seminal_works': []},
 {'id': 'structural-equation-modeling',
  'name': 'Structural Equation Modeling',
  'category': 'quantitative',
  'sub_category': 'Latent Variables',
  'difficulty': 'Advanced',
  'description': 'Estimates relationships among latent constructs while modelling their '
                 'measurement simultaneously.',
  'tags': ['structural equation modeling', 'structural equation model', 'pls-sem'],
  'broad_tags': ['survey'],
  'use_when': ['Constructs are latent and measured with multiple indicators.',
               'The hypotheses form a system with mediating paths.'],
  'assumptions': ['Correctly specified measurement model',
                  'Adequate sample size for the number of parameters',
                  'Multivariate normality for maximum likelihood, or a robust estimator',
                  'No omitted paths that bias the structural estimates'],
  'workflow': ['Specify the measurement model and the structural model separately and in advance.',
               'Assess measurement quality before interpreting any structural path.',
               'Estimate the structural model with an estimator matched to the data.',
               'Report fit indices with the model, not instead of it.',
               'Report the paths you tested and dropped, not only the surviving model.'],
  'diagnostics': ['CFA fit before structural estimation',
                  'CFI / TLI / RMSEA / SRMR',
                  'Composite reliability and average variance extracted',
                  'Discriminant validity checks',
                  'Modification indices treated as exploratory only'],
  'pitfalls': ['Chasing fit indices with modification indices and presenting the result as a '
               'confirmatory test.',
               'Claiming mediation from cross-sectional data collected in one wave.',
               'Reporting fit statistics while ignoring poor discriminant validity.'],
  'related_methods': ['confirmatory-factor-analysis',
                      'mediation',
                      'moderation',
                      'multilevel-modeling'],
  'code_examples': [{'language': 'R',
                     'title': 'R sketch',
                     'code': 'library(lavaan)\n'
                             "model <- '\n"
                             '  autonomy =~ a1 + a2 + a3\n'
                             '  voice    =~ v1 + v2 + v3\n'
                             '  voice ~ autonomy\n'
                             "'\n"
                             'fit <- sem(model, data = df, estimator = "MLR")\n'
                             'summary(fit, fit.measures = TRUE, standardized = TRUE)'},
                    {'language': 'Python',
                     'title': 'Python sketch',
                     'code': 'from semopy import Model\n'
                             '\n'
                             'desc = """\n'
                             'autonomy =~ a1 + a2 + a3\n'
                             'voice =~ v1 + v2 + v3\n'
                             'voice ~ autonomy\n'
                             '"""\n'
                             'model = Model(desc)\n'
                             'model.fit(df)\n'
                             'print(model.inspect())'},
                    {'language': 'Stata',
                     'title': 'Stata sketch',
                     'code': 'sem (Autonomy -> a1 a2 a3) (Voice -> v1 v2 v3) (Autonomy -> Voice), '
                             '///\n'
                             '    method(mlmv)\n'
                             'estat gof, stats(all)'}],
  'source_status': 'curated_scaffold',
  'name_zh': '结构方程模型',
  'description_zh': '在同时建模测量结构的前提下估计潜变量之间的关系。',
  'seminal_works': []},
 {'id': 'confirmatory-factor-analysis',
  'name': 'Confirmatory Factor Analysis',
  'category': 'quantitative',
  'sub_category': 'Measurement',
  'difficulty': 'Intermediate',
  'description': 'Tests whether observed indicators load on latent factors in the pattern the '
                 'theory specifies.',
  'tags': ['confirmatory factor analysis', 'factor analysis'],
  'broad_tags': ['survey'],
  'use_when': ['A measurement structure is hypothesized in advance.',
               'You need evidence of convergent and discriminant validity before structural '
               'modelling.'],
  'assumptions': ['The factor structure is specified before estimation',
                  'Indicators are continuous or treated with an appropriate estimator',
                  'Local independence of residuals unless correlations are theorized'],
  'workflow': ['State the expected factor structure and item assignment.',
               'Estimate the measurement model on its own.',
               'Examine loadings, residual correlations, and fit.',
               'Test discriminant validity across factors.',
               'Test measurement invariance before comparing groups.'],
  'diagnostics': ['Standardized loadings',
                  'Composite reliability',
                  'Average variance extracted',
                  'Heterotrait-monotrait ratio',
                  'Configural / metric / scalar invariance'],
  'pitfalls': ['Freeing residual correlations to improve fit without a substantive reason.',
               'Comparing latent means across groups without establishing scalar invariance.',
               'Reporting Cronbach’s alpha alone as evidence of construct validity.'],
  'related_methods': ['structural-equation-modeling', 'multilevel-modeling', 'mediation'],
  'code_examples': [{'language': 'R',
                     'title': 'R sketch',
                     'code': 'library(lavaan)\n'
                             "cfa_model <- '\n"
                             '  engagement =~ e1 + e2 + e3\n'
                             '  burnout    =~ b1 + b2 + b3\n'
                             "'\n"
                             'fit <- cfa(cfa_model, data = df, estimator = "MLR")\n'
                             'summary(fit, fit.measures = TRUE, standardized = TRUE)\n'
                             'semTools::compRelSEM(fit)'},
                    {'language': 'Python',
                     'title': 'Python sketch',
                     'code': 'from semopy import Model, calc_stats\n'
                             '\n'
                             'desc = """\n'
                             'engagement =~ e1 + e2 + e3\n'
                             'burnout =~ b1 + b2 + b3\n'
                             '"""\n'
                             'm = Model(desc)\n'
                             'm.fit(df)\n'
                             'print(calc_stats(m))'},
                    {'language': 'Stata',
                     'title': 'Stata sketch',
                     'code': 'sem (Engagement -> e1 e2 e3) (Burnout -> b1 b2 b3), standardized\n'
                             'estat gof, stats(all)'}],
  'source_status': 'curated_scaffold',
  'name_zh': '验证性因子分析',
  'description_zh': '检验观测指标是否按理论设定的模式负载于潜在因子。',
  'seminal_works': []},
 {'id': 'multilevel-modeling',
  'name': 'Multilevel Modeling',
  'category': 'quantitative',
  'sub_category': 'Hierarchical Data',
  'difficulty': 'Advanced',
  'description': 'Models outcomes for observations nested in higher-level units, separating '
                 'within- from between-group effects.',
  'tags': ['multilevel modeling',
           'multilevel models',
           'multilevel analysis',
           'hierarchical linear modeling',
           'mixed effects model'],
  'broad_tags': ['survey'],
  'use_when': ['Observations are nested (employees in teams, students in schools, days in '
               'persons).',
               'You want to model group-level variance rather than treat it as nuisance.'],
  'assumptions': ['Correct specification of levels and random effects',
                  'Level-1 residuals independent conditional on random effects',
                  'Sufficient number of higher-level units to estimate variance components',
                  'Random effects uncorrelated with predictors unless modelled'],
  'workflow': ['Map the nesting structure and count units at each level.',
               'Fit the null model and report the intraclass correlation.',
               'Add level-1 predictors, centring them explicitly.',
               'Add level-2 predictors and any cross-level interactions.',
               'Compare nested models with a stated criterion.'],
  'diagnostics': ['Intraclass correlation',
                  'Random slope variance tests',
                  'Level-2 sample size adequacy',
                  'Residual diagnostics at both levels'],
  'pitfalls': ['Leaving centring implicit, which conflates within- and between-group effects.',
               'Estimating random slopes with too few level-2 units.',
               'Interpreting a cross-level interaction without a random slope for the level-1 '
               'predictor.'],
  'related_methods': ['panel-data', 'random-effects', 'structural-equation-modeling', 'moderation'],
  'code_examples': [{'language': 'R',
                     'title': 'R sketch',
                     'code': 'library(lme4)\n'
                             'null <- lmer(y ~ 1 + (1 | team), data = df)\n'
                             'performance::icc(null)\n'
                             '\n'
                             'fit <- lmer(y ~ x_within_c + x_between_c + (1 + x_within_c | team), '
                             'data = df)\n'
                             'summary(fit)'},
                    {'language': 'Python',
                     'title': 'Python sketch',
                     'code': 'import statsmodels.formula.api as smf\n'
                             '\n'
                             'null = smf.mixedlm("y ~ 1", df, groups=df["team"]).fit()\n'
                             'fit = smf.mixedlm("y ~ x_within_c + x_between_c", df,\n'
                             '                  groups=df["team"], '
                             're_formula="~x_within_c").fit()\n'
                             'print(fit.summary())'},
                    {'language': 'Stata',
                     'title': 'Stata sketch',
                     'code': 'mixed y || team:\n'
                             'estat icc\n'
                             'mixed y x_within_c x_between_c || team: x_within_c, '
                             'covariance(unstructured)'}],
  'source_status': 'curated_scaffold',
  'name_zh': '多层线性模型',
  'description_zh': '为嵌套结构的数据建模，分离组内效应与组间效应。',
  'seminal_works': []},
 {'id': 'mediation',
  'name': 'Mediation Analysis',
  'category': 'quantitative',
  'sub_category': 'Mechanisms',
  'difficulty': 'Intermediate',
  'description': 'Decomposes an effect into a path running through an intervening variable and a '
                 'remaining direct path.',
  'tags': ['mediation analysis',
           'moderated mediation',
           'sequential mediation',
           'moderated mediation model'],
  'broad_tags': ['survey'],
  'use_when': ['A theorized mechanism links the predictor to the outcome.',
               'The mediator is measured before the outcome, ideally in a separate wave.'],
  'assumptions': ['Temporal order predictor → mediator → outcome',
                  'No unmeasured confounding of the mediator–outcome path',
                  'No treatment–mediator interaction unless modelled',
                  'Reliable mediator measurement'],
  'workflow': ['State the mechanism and why the mediator captures it.',
               'Establish temporal separation in the design, not after the fact.',
               'Estimate the indirect effect with bootstrap confidence intervals.',
               'Report direct and total effects alongside the indirect effect.',
               'Assess sensitivity to mediator–outcome confounding.'],
  'diagnostics': ['Bootstrap confidence intervals for the indirect effect',
                  'Sensitivity analysis for unmeasured confounding',
                  'Alternative mediator ordering',
                  'Measurement reliability of the mediator'],
  'pitfalls': ['Claiming mediation from cross-sectional data where all three variables were '
               'measured at once.',
               'Treating a significant indirect effect as proof of the mechanism when the mediator '
               'is confounded.',
               'Relying on the outdated requirement of a significant total effect before testing '
               'mediation.'],
  'related_methods': ['structural-equation-modeling', 'moderation', 'multilevel-modeling'],
  'code_examples': [{'language': 'R',
                     'title': 'R sketch',
                     'code': 'library(mediation)\n'
                             'm <- lm(mediator ~ treat + x1, data = df)\n'
                             'y <- lm(outcome ~ treat + mediator + x1, data = df)\n'
                             'out <- mediate(m, y, treat = "treat", mediator = "mediator", boot = '
                             'TRUE, sims = 5000)\n'
                             'summary(out)\n'
                             'sensitivity <- medsens(out); summary(sensitivity)'},
                    {'language': 'Python',
                     'title': 'Python sketch',
                     'code': 'import statsmodels.api as sm\n'
                             'from statsmodels.stats.mediation import Mediation\n'
                             'import statsmodels.formula.api as smf\n'
                             '\n'
                             'med = smf.ols("mediator ~ treat + x1", df)\n'
                             'out = smf.ols("outcome ~ treat + mediator + x1", df)\n'
                             'res = Mediation(out, med, "treat", "mediator").fit(n_rep=5000)\n'
                             'print(res.summary())'},
                    {'language': 'Stata',
                     'title': 'Stata sketch',
                     'code': 'sem (mediator <- treat x1) (outcome <- mediator treat x1), '
                             'vce(bootstrap, reps(5000))\n'
                             'estat teffects'}],
  'source_status': 'curated_scaffold',
  'name_zh': '中介效应分析',
  'description_zh': '将总效应分解为经由中介变量的间接路径与剩余的直接路径。',
  'seminal_works': []},
 {'id': 'moderation',
  'name': 'Moderation Analysis',
  'category': 'quantitative',
  'sub_category': 'Heterogeneous Effects',
  'difficulty': 'Intermediate',
  'description': 'Tests whether the strength or direction of a relationship depends on a third '
                 'variable.',
  'tags': ['moderation analysis',
           'moderated regression',
           'moderating effects',
           'interaction effects',
           'interaction analysis'],
  'broad_tags': ['survey'],
  'use_when': ['Theory predicts a boundary condition rather than a uniform effect.',
               'You expect the effect to differ across contexts or people.'],
  'assumptions': ['Correct functional form for the interaction',
                  'Adequate variance and overlap in the moderator',
                  'Reliable measurement of both interacting variables',
                  'Sufficient power, which interactions need much more of than main effects'],
  'workflow': ['State the predicted direction of the interaction in advance.',
               'Centre or standardize the interacting variables and say so.',
               'Include both constituent terms with the product.',
               'Probe simple slopes across meaningful moderator values.',
               'Plot the interaction over the observed moderator range only.'],
  'diagnostics': ['Simple slope tests',
                  'Johnson–Neyman region of significance',
                  'Interaction plots restricted to observed data',
                  'Power assessment for the interaction'],
  'pitfalls': ['Interpreting a constituent term as a main effect when the product is in the model; '
               'it is the effect at moderator = 0.',
               'Extrapolating simple slopes beyond the observed moderator range.',
               'Testing many interactions and reporting only the significant one.'],
  'related_methods': ['mediation', 'multilevel-modeling', 'ols-regression'],
  'code_examples': [{'language': 'R',
                     'title': 'R sketch',
                     'code': 'df$x_c <- scale(df$x, scale = FALSE)\n'
                             'df$m_c <- scale(df$m, scale = FALSE)\n'
                             'fit <- lm(y ~ x_c * m_c + controls, data = df)\n'
                             '\n'
                             'library(interactions)\n'
                             'sim_slopes(fit, pred = x_c, modx = m_c, johnson_neyman = TRUE)\n'
                             'interact_plot(fit, pred = x_c, modx = m_c)'},
                    {'language': 'Python',
                     'title': 'Python sketch',
                     'code': 'import statsmodels.formula.api as smf\n'
                             '\n'
                             'df["x_c"] = df["x"] - df["x"].mean()\n'
                             'df["m_c"] = df["m"] - df["m"].mean()\n'
                             'fit = smf.ols("y ~ x_c * m_c + controls", data=df).fit()\n'
                             'print(fit.summary())'},
                    {'language': 'Stata',
                     'title': 'Stata sketch',
                     'code': 'center x m, prefix(c_)\n'
                             'regress y c.c_x##c.c_m controls\n'
                             'margins, dydx(c_x) at(c_m = (-1 0 1))\n'
                             'marginsplot'}],
  'source_status': 'curated_scaffold',
  'name_zh': '调节效应分析',
  'description_zh': '检验某一关系的强度或方向是否依赖于第三个变量。',
  'seminal_works': []},
 {'id': 'meta-analysis',
  'name': 'Meta-Analysis',
  'category': 'quantitative',
  'sub_category': 'Evidence Synthesis',
  'difficulty': 'Advanced',
  'description': 'Pools effect sizes across studies and models the sources of variation between '
                 'them.',
  'tags': ['meta_analysis', 'meta-analysis'],
  'broad_tags': [],
  'use_when': ['A body of quantitative studies estimates a comparable relationship.',
               'You want a pooled estimate and an account of heterogeneity.'],
  'assumptions': ['Comparable effect-size definitions across studies',
                  'Independence of effect sizes, or explicit modelling of dependence',
                  'Search and inclusion criteria fixed before coding',
                  'Publication and reporting bias assessed rather than assumed away'],
  'workflow': ['Pre-register the search strategy, databases, and inclusion rules.',
               'Screen and code studies with at least two independent coders.',
               'Convert estimates to a common effect-size metric.',
               'Fit a random-effects model and quantify heterogeneity.',
               'Run moderator analyses only for pre-specified moderators.',
               'Assess publication bias with multiple complementary methods.'],
  'diagnostics': ['I² and τ² heterogeneity statistics',
                  'Funnel plot and Egger test',
                  'Trim-and-fill or selection models',
                  'Leave-one-out influence analysis',
                  'Inter-coder reliability'],
  'pitfalls': ['Pooling effect sizes that answer materially different questions.',
               'Treating multiple effect sizes from one sample as independent.',
               'Running many post-hoc moderator analyses and reporting the significant ones.'],
  'related_methods': ['ols-regression', 'structural-equation-modeling'],
  'code_examples': [{'language': 'R',
                     'title': 'R sketch',
                     'code': 'library(metafor)\n'
                             'res <- rma(yi = effect, vi = variance, data = studies, method = '
                             '"REML")\n'
                             'summary(res)\n'
                             'funnel(res); regtest(res)\n'
                             'res_mod <- rma(yi = effect, vi = variance, mods = ~ design, data = '
                             'studies)'},
                    {'language': 'Python',
                     'title': 'Python sketch',
                     'code': 'from statsmodels.stats.meta_analysis import combine_effects\n'
                             '\n'
                             'res = combine_effects(studies["effect"], studies["variance"],\n'
                             '                      method_re="dl", use_t=True)\n'
                             'print(res.summary_frame())'},
                    {'language': 'Stata',
                     'title': 'Stata sketch',
                     'code': 'meta set effect se, random(reml)\n'
                             'meta summarize\n'
                             'meta funnelplot\n'
                             'meta bias, egger\n'
                             'meta regress design'}],
  'source_status': 'curated_scaffold',
  'name_zh': '元分析',
  'description_zh': '汇总多项研究的效应量，并对研究间异质性的来源建模。',
  'seminal_works': []},
 {'id': 'experiment',
  'name': 'Experiment (General)',
  'category': 'experimental',
  'sub_category': 'Causal Design',
  'difficulty': 'Intermediate',
  'description': 'Randomly assigns units to conditions so that differences in outcomes can be '
                 'attributed to the manipulation.',
  'tags': ['experiment'],
  'broad_tags': [],
  'use_when': ['You control the assignment of the treatment.',
               'The causal question concerns a manipulable factor.'],
  'assumptions': ['Successful randomization',
                  'No interference between units',
                  'Manipulation actually changes the intended construct',
                  'Outcome measurement is not differentially affected by condition'],
  'workflow': ['State hypotheses and the analysis plan before collecting data.',
               'Determine sample size from a power analysis for the smallest effect of interest.',
               'Randomize at the level at which treatment is delivered.',
               'Verify the manipulation worked and check balance.',
               'Analyse as randomized, reporting attrition by condition.'],
  'diagnostics': ['Randomization balance table',
                  'Manipulation check',
                  'Attrition by condition',
                  'Pre-registration deviation report'],
  'pitfalls': ['Excluding participants after seeing the outcome, which breaks randomization.',
               'Running a manipulation check that is affected by the outcome itself.',
               'Underpowering the study and interpreting a null as evidence of no effect.'],
  'related_methods': ['lab-experiment',
                      'field-experiment',
                      'randomized-controlled-trial',
                      'survey-experiment'],
  'code_examples': [{'language': 'R',
                     'title': 'R sketch',
                     'code': 'fit <- lm(outcome ~ condition, data = df)\n'
                             'summary(fit)\n'
                             '\n'
                             'library(pwr)\n'
                             'pwr.t.test(d = 0.3, sig.level = 0.05, power = 0.8)'},
                    {'language': 'Python',
                     'title': 'Python sketch',
                     'code': 'import statsmodels.formula.api as smf\n'
                             'from statsmodels.stats.power import TTestIndPower\n'
                             '\n'
                             'print(TTestIndPower().solve_power(effect_size=0.3, alpha=0.05, '
                             'power=0.8))\n'
                             'print(smf.ols("outcome ~ C(condition)", data=df).fit().summary())'},
                    {'language': 'Stata',
                     'title': 'Stata sketch',
                     'code': 'power twomeans 0, sd(1) diff(0.3) power(0.8)\n'
                             'regress outcome i.condition, vce(robust)'}],
  'source_status': 'curated_scaffold',
  'name_zh': '实验法（总述）',
  'description_zh': '将个体随机分配到不同条件，使结果差异可归因于操纵本身。',
  'seminal_works': []},
 {'id': 'lab-experiment',
  'name': 'Lab Experiment',
  'category': 'experimental',
  'sub_category': 'Causal Design',
  'difficulty': 'Intermediate',
  'description': 'Runs a controlled manipulation in a setting the researcher fully controls, '
                 'maximizing internal validity.',
  'tags': ['lab_experiment_data', 'lab experiments', 'laboratory experiment'],
  'broad_tags': ['experiment'],
  'use_when': ['You need tight control over the stimulus and the environment.',
               'The mechanism matters more than immediate field generalizability.'],
  'assumptions': ['Random assignment within the lab session',
                  'Participants engage with the task as intended',
                  'No cross-condition contamination between participants'],
  'workflow': ['Design the stimulus and pilot it for comprehension.',
               'Pre-register hypotheses, exclusions, and the analysis plan.',
               'Randomize within session and counterbalance order effects.',
               'Collect manipulation and attention checks.',
               'Report all conditions and measures collected.'],
  'diagnostics': ['Attention and comprehension checks',
                  'Order-effect tests',
                  'Session-level clustering checks',
                  'Exclusion sensitivity analysis'],
  'pitfalls': ['Applying attention-check exclusions that differ by condition.',
               'Treating a student convenience sample as representative without saying so.',
               'Reporting only the conditions that worked.'],
  'related_methods': ['experiment', 'field-experiment', 'vignette-experiment', 'survey-experiment'],
  'code_examples': [{'language': 'R',
                     'title': 'R sketch',
                     'code': 'fit <- lm(outcome ~ condition + order, data = df)\n'
                             'summary(fit)\n'
                             'car::Anova(fit, type = 3)'},
                    {'language': 'Python',
                     'title': 'Python sketch',
                     'code': 'import statsmodels.formula.api as smf\n'
                             '\n'
                             'fit = smf.ols("outcome ~ C(condition) + C(order)", data=df).fit()\n'
                             'print(smf.stats.anova_lm(fit, typ=3))'},
                    {'language': 'Stata',
                     'title': 'Stata sketch',
                     'code': 'anova outcome condition order\n'
                             'margins condition, pwcompare(effects)'}],
  'source_status': 'curated_scaffold',
  'name_zh': '实验室实验',
  'description_zh': '在研究者完全控制的环境中实施操纵，最大化内部效度。',
  'seminal_works': []},
 {'id': 'field-experiment',
  'name': 'Field Experiment',
  'category': 'experimental',
  'sub_category': 'Causal Design',
  'difficulty': 'Advanced',
  'description': 'Randomizes treatment in a real organizational or market setting where '
                 'participants act naturally.',
  'tags': ['field_experiment_data', 'field experiment'],
  'broad_tags': ['experiment'],
  'use_when': ['You can randomize in the actual setting of interest.',
               'Ecological validity is central to the contribution.'],
  'assumptions': ['Randomization is implemented as designed in the field',
                  'No spillover between treated and control units',
                  'Outcome data collection is not affected by condition',
                  'Compliance is measured, not assumed'],
  'workflow': ['Agree the randomization protocol with the partner organization in writing.',
               'Register the design and primary outcome before launch.',
               'Randomize at the level where spillover is contained.',
               'Track compliance and attrition throughout.',
               'Report intent-to-treat as the primary estimate.'],
  'diagnostics': ['Balance on baseline covariates',
                  'Compliance and take-up rates',
                  'Differential attrition tests',
                  'Spillover checks across units'],
  'pitfalls': ['Reporting treatment-on-the-treated as the headline result without the '
               'intent-to-treat estimate.',
               'Randomizing individuals when the treatment plainly spills across a team.',
               'Letting the partner organization reassign participants mid-study.'],
  'related_methods': ['experiment',
                      'randomized-controlled-trial',
                      'lab-experiment',
                      'difference-in-differences'],
  'code_examples': [{'language': 'R',
                     'title': 'R sketch',
                     'code': 'itt <- lm(outcome ~ assigned, data = df)\n'
                             'late <- AER::ivreg(outcome ~ received | assigned, data = df)\n'
                             'summary(itt); summary(late, diagnostics = TRUE)'},
                    {'language': 'Python',
                     'title': 'Python sketch',
                     'code': 'import statsmodels.formula.api as smf\n'
                             'from linearmodels.iv import IV2SLS\n'
                             '\n'
                             'itt = smf.ols("outcome ~ assigned", data=df).fit(cov_type="HC1")\n'
                             'late = IV2SLS.from_formula("outcome ~ 1 + [received ~ assigned]", '
                             'df).fit()\n'
                             'print(itt.summary()); print(late)'},
                    {'language': 'Stata',
                     'title': 'Stata sketch',
                     'code': 'regress outcome assigned, vce(cluster site)\n'
                             'ivregress 2sls outcome (received = assigned), vce(cluster site)'}],
  'source_status': 'curated_scaffold',
  'name_zh': '田野实验',
  'description_zh': '在真实组织或市场情境中随机分配处理，参与者行为自然发生。',
  'seminal_works': []},
 {'id': 'randomized-controlled-trial',
  'name': 'Randomized Controlled Trial',
  'category': 'experimental',
  'sub_category': 'Causal Design',
  'difficulty': 'Advanced',
  'description': 'A pre-registered trial with randomized allocation, a protocol, and pre-specified '
                 'primary outcomes.',
  'tags': ['randomized controlled trial', 'randomized controlled trials', 'randomized evaluation'],
  'broad_tags': ['experiment'],
  'use_when': ['The intervention is well defined and deliverable at scale.',
               'A registered protocol and primary outcome are appropriate for the claim.'],
  'assumptions': ['Allocation concealment',
                  'Pre-specified primary outcome',
                  'Analysis follows the registered plan',
                  'Attrition handled per protocol'],
  'workflow': ['Write and register the protocol including the primary outcome and analysis plan.',
               'Compute the sample size for the primary outcome.',
               'Randomize with concealed allocation.',
               'Follow participants and document losses in a flow diagram.',
               'Analyse by intention to treat and report all pre-specified outcomes.'],
  'diagnostics': ['CONSORT-style participant flow',
                  'Baseline comparability table',
                  'Protocol deviation log',
                  'Pre-specified vs exploratory outcome separation'],
  'pitfalls': ['Switching the primary outcome after seeing the data.',
               'Reporting per-protocol results without the intention-to-treat analysis.',
               'Presenting exploratory subgroup findings with the same confidence as the primary '
               'result.'],
  'related_methods': ['field-experiment', 'experiment', 'meta-analysis'],
  'code_examples': [{'language': 'R',
                     'title': 'R sketch',
                     'code': 'itt <- lm(primary_outcome ~ arm, data = trial)\n'
                             'summary(itt)\n'
                             'table(trial$arm, trial$completed)'},
                    {'language': 'Python',
                     'title': 'Python sketch',
                     'code': 'import statsmodels.formula.api as smf\n'
                             '\n'
                             'itt = smf.ols("primary_outcome ~ C(arm)", '
                             'data=trial).fit(cov_type="HC1")\n'
                             'print(itt.summary())\n'
                             'print(trial.groupby("arm")["completed"].mean())'},
                    {'language': 'Stata',
                     'title': 'Stata sketch',
                     'code': 'regress primary_outcome i.arm, vce(robust)\n'
                             'tabulate arm completed, row chi2'}],
  'source_status': 'curated_scaffold',
  'name_zh': '随机对照试验',
  'description_zh': '带有注册方案与预设主要结局的随机分配试验。',
  'seminal_works': []},
 {'id': 'survey-experiment',
  'name': 'Survey Experiment',
  'category': 'experimental',
  'sub_category': 'Causal Design',
  'difficulty': 'Intermediate',
  'description': 'Embeds randomized manipulations inside a survey instrument delivered to a '
                 'defined sample.',
  'tags': ['survey experiment', 'survey experiments'],
  'broad_tags': ['experiment', 'survey'],
  'use_when': ['You want randomized variation with a broader sample than a lab allows.',
               'The manipulation can be delivered as text, image, or question wording.'],
  'assumptions': ['Random assignment within the survey instrument',
                  'Respondents read and process the manipulation',
                  'No differential dropout across conditions',
                  'The stated response reflects the construct of interest'],
  'workflow': ['Design the vignette or wording manipulation and pilot for clarity.',
               'Pre-register conditions, exclusions, and analysis.',
               'Randomize condition and item order within the instrument.',
               'Measure attention and comprehension.',
               'Report dropout by condition and analyse as randomized.'],
  'diagnostics': ['Dropout by condition',
                  'Attention-check pass rates',
                  'Order-effect tests',
                  'Balance on demographics'],
  'pitfalls': ['Measuring stated intention and reporting it as behaviour.',
               'Dropping inattentive respondents at different rates across conditions.',
               'Using a panel sample and describing it as representative without weighting.'],
  'related_methods': ['vignette-experiment', 'conjoint-experiment', 'experiment', 'lab-experiment'],
  'code_examples': [{'language': 'R',
                     'title': 'R sketch',
                     'code': 'fit <- lm(intention ~ condition, data = survey)\n'
                             'summary(fit)\n'
                             'chisq.test(table(survey$condition, survey$dropped))'},
                    {'language': 'Python',
                     'title': 'Python sketch',
                     'code': 'import statsmodels.formula.api as smf\n'
                             'import scipy.stats as st\n'
                             '\n'
                             'fit = smf.ols("intention ~ C(condition)", '
                             'data=survey).fit(cov_type="HC1")\n'
                             'print(fit.summary())\n'
                             'print(st.chi2_contingency(pd.crosstab(survey.condition, '
                             'survey.dropped)))'},
                    {'language': 'Stata',
                     'title': 'Stata sketch',
                     'code': 'regress intention i.condition, vce(robust)\n'
                             'tabulate condition dropped, chi2'}],
  'source_status': 'curated_scaffold',
  'name_zh': '调查实验',
  'description_zh': '将随机化操纵嵌入问卷工具，投放给界定好的样本。',
  'seminal_works': []},
 {'id': 'vignette-experiment',
  'name': 'Vignette Experiment',
  'category': 'experimental',
  'sub_category': 'Causal Design',
  'difficulty': 'Intermediate',
  'description': 'Presents systematically varied scenario descriptions and measures judgements or '
                 'stated choices.',
  'tags': ['vignette analysis', 'vignette experiment', 'vignette study'],
  'broad_tags': ['experiment'],
  'use_when': ['The factors of interest can be described credibly in a scenario.',
               'Real-world manipulation would be impractical or unethical.'],
  'assumptions': ['Respondents interpret the vignette as intended',
                  'Dimensions vary orthogonally across vignettes',
                  'Stated judgement relates meaningfully to the target construct'],
  'workflow': ['Define the vignette dimensions and their levels.',
               'Generate the vignette set so dimensions vary independently.',
               'Assign vignettes at random, balancing exposure.',
               'Measure the judgement immediately after the vignette.',
               'Analyse with dimension-level effects, clustering by respondent for multiple '
               'vignettes.'],
  'diagnostics': ['Dimension orthogonality check',
                  'Respondent-level clustering',
                  'Realism and comprehension ratings',
                  'Fatigue tests across vignette order'],
  'pitfalls': ['Confounding two dimensions in the vignette text so their effects cannot be '
               'separated.',
               'Treating repeated vignettes from one respondent as independent observations.',
               'Generalizing stated judgements directly to field behaviour.'],
  'related_methods': ['survey-experiment', 'conjoint-experiment', 'lab-experiment'],
  'code_examples': [{'language': 'R',
                     'title': 'R sketch',
                     'code': 'library(lme4)\n'
                             'fit <- lmer(rating ~ dim_a + dim_b + dim_c + (1 | respondent), data '
                             '= vignettes)\n'
                             'summary(fit)'},
                    {'language': 'Python',
                     'title': 'Python sketch',
                     'code': 'import statsmodels.formula.api as smf\n'
                             '\n'
                             'fit = smf.mixedlm("rating ~ dim_a + dim_b + dim_c", vignettes,\n'
                             '                  groups=vignettes["respondent"]).fit()\n'
                             'print(fit.summary())'},
                    {'language': 'Stata',
                     'title': 'Stata sketch',
                     'code': 'mixed rating i.dim_a i.dim_b i.dim_c || respondent:\nmargins dim_a'}],
  'source_status': 'curated_scaffold',
  'name_zh': '情境实验',
  'description_zh': '呈现系统性变化的情境描述，测量判断或陈述性选择。',
  'seminal_works': []},
 {'id': 'conjoint-experiment',
  'name': 'Conjoint Experiment',
  'category': 'experimental',
  'sub_category': 'Causal Design',
  'difficulty': 'Advanced',
  'description': 'Asks respondents to choose between profiles whose attributes are randomized, '
                 'recovering the effect of each attribute.',
  'tags': ['conjoint analysis', 'choice-based conjoint analysis', 'conjoint experiment'],
  'broad_tags': ['experiment'],
  'use_when': ['You need the relative weight of several attributes simultaneously.',
               'Choice between alternatives is the natural response format.'],
  'assumptions': ['Attributes are randomized independently',
                  'No profile combinations are implausible enough to be dismissed',
                  'Stability across task repetitions',
                  'Respondents evaluate profiles rather than satisficing'],
  'workflow': ['Define attributes and levels grounded in the decision being modelled.',
               'Randomize attribute levels and profile order.',
               'Present a manageable number of tasks per respondent.',
               'Estimate average marginal component effects.',
               'Check for profile-order and attribute-order effects.'],
  'diagnostics': ['Attribute balance checks',
                  'Carryover and profile-order tests',
                  'Respondent-clustered standard errors',
                  'Task-number fatigue analysis'],
  'pitfalls': ['Including attribute combinations respondents find impossible, which distorts the '
               'estimates.',
               'Ignoring respondent-level clustering across repeated choice tasks.',
               'Reading an average marginal component effect as a preference share.'],
  'related_methods': ['survey-experiment', 'vignette-experiment', 'logistic-regression'],
  'code_examples': [{'language': 'R',
                     'title': 'R sketch',
                     'code': 'library(cjoint)\n'
                             'fit <- amce(choice ~ attr_pay + attr_flex + attr_autonomy,\n'
                             '            data = conjoint, cluster = TRUE, respondent.id = "rid")\n'
                             'summary(fit); plot(fit)'},
                    {'language': 'Python',
                     'title': 'Python sketch',
                     'code': 'import statsmodels.formula.api as smf\n'
                             '\n'
                             'fit = smf.ols("choice ~ C(attr_pay) + C(attr_flex) + '
                             'C(attr_autonomy)",\n'
                             '              data=conjoint).fit(cov_type="cluster",\n'
                             '                                 cov_kwds={"groups": '
                             'conjoint["rid"]})\n'
                             'print(fit.summary())'},
                    {'language': 'Stata',
                     'title': 'Stata sketch',
                     'code': 'regress choice i.attr_pay i.attr_flex i.attr_autonomy, vce(cluster '
                             'rid)\n'
                             'margins, dydx(*)'}],
  'source_status': 'curated_scaffold',
  'name_zh': '联合分析实验',
  'description_zh': '让受访者在属性随机化的方案之间选择，从而还原每个属性的效应。',
  'seminal_works': []},
 {'id': 'topic-modeling',
  'name': 'Topic Modeling',
  'category': 'computational',
  'sub_category': 'Text Analysis',
  'difficulty': 'Intermediate',
  'description': 'Induces latent themes from a document collection as distributions over words.',
  'tags': ['topic modeling',
           'topic model',
           'lda',
           'latent dirichlet allocation',
           'structural topic model'],
  'broad_tags': ['text_mining', 'nlp', 'machine_learning'],
  'use_when': ['You need structure in a corpus too large to read.',
               'Themes are exploratory input rather than a confirmatory test.'],
  'assumptions': ['Documents are exchangeable bags of words within the model',
                  'The chosen number of topics reflects a defensible criterion',
                  'Preprocessing choices do not silently determine the result'],
  'workflow': ['Define the corpus and document unit explicitly.',
               'Document every preprocessing step, since they change the output.',
               'Select the topic count with a stated criterion, not by eye alone.',
               'Fit the model with a fixed random seed.',
               'Validate topics by reading samples of top documents, not only top words.',
               'Label topics through independent human coding.'],
  'diagnostics': ['Coherence and exclusivity scores',
                  'Held-out likelihood',
                  'Stability across seeds',
                  'Human validation of topic labels'],
  'pitfalls': ['Naming a topic from its top ten words without reading any documents.',
               'Presenting topic proportions as measured constructs in a downstream regression '
               'without validation.',
               'Reporting one seed when topics shift across runs.'],
  'related_methods': ['text-classification',
                      'embeddings',
                      'computational-content-analysis',
                      'content-analysis'],
  'code_examples': [{'language': 'R',
                     'title': 'R sketch',
                     'code': 'library(stm)\n'
                             'processed <- textProcessor(df$text, metadata = df)\n'
                             'out <- prepDocuments(processed$documents, processed$vocab, '
                             'processed$meta)\n'
                             'fit <- stm(out$documents, out$vocab, K = 20, data = out$meta, seed = '
                             '42)\n'
                             'labelTopics(fit); findThoughts(fit, texts = df$text, n = 5)'},
                    {'language': 'Python',
                     'title': 'Python sketch',
                     'code': 'from sklearn.feature_extraction.text import CountVectorizer\n'
                             'from sklearn.decomposition import LatentDirichletAllocation\n'
                             '\n'
                             'X = CountVectorizer(min_df=5, '
                             'stop_words="english").fit_transform(df["text"])\n'
                             'lda = LatentDirichletAllocation(n_components=20, '
                             'random_state=42).fit(X)\n'
                             'print(lda.perplexity(X))'},
                    {'language': 'Stata',
                     'title': 'Stata sketch',
                     'code': '* Stata has no first-class topic model; call the analysis script '
                             'and\n'
                             '* read the fitted document-topic matrix back in.\n'
                             'shell python topic_model.py --k 20 --seed 42\n'
                             'import delimited using doc_topics.csv, clear'}],
  'source_status': 'curated_scaffold',
  'name_zh': '主题模型',
  'description_zh': '从文档集合中归纳出以词分布表示的潜在主题。',
  'seminal_works': []},
 {'id': 'text-classification',
  'name': 'Text Classification',
  'category': 'computational',
  'sub_category': 'Text Analysis',
  'difficulty': 'Intermediate',
  'description': 'Assigns documents to predefined categories using a model trained on labelled '
                 'examples.',
  'tags': ['text classification', 'text classifier', 'document classification'],
  'broad_tags': ['nlp', 'machine_learning'],
  'use_when': ['The categories are defined in advance by theory or a codebook.',
               'Hand coding the full corpus is infeasible but a labelled sample is not.'],
  'assumptions': ['Training labels are reliable',
                  'Training and target corpora are drawn from comparable distributions',
                  'Evaluation uses data never seen in training or tuning'],
  'workflow': ['Write the codebook and measure inter-coder reliability before modelling.',
               'Draw and hand-label a random training sample.',
               'Split into train, validation, and a held-out test set once.',
               'Train the model and tune only on validation data.',
               'Report held-out performance per class, not only overall accuracy.',
               'Audit errors qualitatively before using predictions downstream.'],
  'diagnostics': ['Per-class precision, recall, F1',
                  'Confusion matrix',
                  'Inter-coder reliability of the training labels',
                  'Performance across subgroups'],
  'pitfalls': ['Reporting overall accuracy for an imbalanced corpus where the majority class '
               'dominates.',
               'Tuning on the test set and reporting it as held-out performance.',
               'Feeding predicted labels into a regression without accounting for classification '
               'error.'],
  'related_methods': ['topic-modeling',
                      'embeddings',
                      'computational-content-analysis',
                      'content-analysis'],
  'code_examples': [{'language': 'R',
                     'title': 'R sketch',
                     'code': 'library(quanteda); library(quanteda.textmodels)\n'
                             'dfmat <- dfm(tokens(corpus(train$text)))\n'
                             'fit <- textmodel_nb(dfmat, train$label)\n'
                             'pred <- predict(fit, newdata = '
                             'dfm_match(dfm(tokens(corpus(test$text))), featnames(dfmat)))\n'
                             'caret::confusionMatrix(pred, factor(test$label))'},
                    {'language': 'Python',
                     'title': 'Python sketch',
                     'code': 'from sklearn.pipeline import make_pipeline\n'
                             'from sklearn.feature_extraction.text import TfidfVectorizer\n'
                             'from sklearn.linear_model import LogisticRegression\n'
                             'from sklearn.metrics import classification_report\n'
                             '\n'
                             'clf = make_pipeline(TfidfVectorizer(min_df=3), '
                             'LogisticRegression(max_iter=1000))\n'
                             'clf.fit(train["text"], train["label"])\n'
                             'print(classification_report(test["label"], '
                             'clf.predict(test["text"])))'},
                    {'language': 'Stata',
                     'title': 'Stata sketch',
                     'code': '* Train outside Stata, then merge predictions and audit them.\n'
                             'shell python classify.py --in corpus.csv --out preds.csv\n'
                             'import delimited using preds.csv, clear\n'
                             'tabulate true_label predicted_label'}],
  'source_status': 'curated_scaffold',
  'name_zh': '文本分类',
  'description_zh': '用带标注样本训练模型，将文档归入预先定义的类别。',
  'seminal_works': []},
 {'id': 'embeddings',
  'name': 'Embeddings',
  'category': 'computational',
  'sub_category': 'Representation Learning',
  'difficulty': 'Advanced',
  'description': 'Represents words, documents, or entities as dense vectors whose geometry encodes '
                 'similarity.',
  'tags': ['embeddings',
           'word embeddings',
           'sentence embeddings',
           'document embeddings',
           'continuous-time embedding'],
  'broad_tags': ['nlp', 'machine_learning'],
  'use_when': ['You need graded similarity rather than exact term matching.',
               'The construct of interest is semantic rather than lexical.'],
  'assumptions': ['The embedding model’s training domain is close enough to the corpus',
                  'Similarity in the vector space corresponds to the intended construct',
                  'Comparisons use a consistent model version'],
  'workflow': ['State what similarity is supposed to mean for the research question.',
               'Choose and pin an embedding model version.',
               'Encode documents with documented preprocessing.',
               'Validate the space against human judgements on a sample.',
               'Report the model, version, and dimensionality used.'],
  'diagnostics': ['Human validation on a held-out similarity sample',
                  'Nearest-neighbour inspection',
                  'Stability across model versions',
                  'Bias audits on socially salient dimensions'],
  'pitfalls': ['Treating cosine similarity as a validated measure of a theoretical construct '
               'without human checks.',
               'Comparing results across embedding model versions as if the spaces were identical.',
               'Ignoring that pretrained embeddings encode social biases relevant to the outcome.'],
  'related_methods': ['topic-modeling', 'text-classification', 'network-analysis'],
  'code_examples': [{'language': 'R',
                     'title': 'R sketch',
                     'code': 'library(text)\n'
                             'emb <- textEmbed(df$text, model = '
                             '"sentence-transformers/all-MiniLM-L6-v2")\n'
                             'sim <- text::textSimilarity(emb$texts$texts[1, ], emb$texts$texts[2, '
                             '])'},
                    {'language': 'Python',
                     'title': 'Python sketch',
                     'code': 'from sentence_transformers import SentenceTransformer\n'
                             'from sklearn.metrics.pairwise import cosine_similarity\n'
                             '\n'
                             'model = SentenceTransformer("all-MiniLM-L6-v2")  # pin the version\n'
                             'vecs = model.encode(df["text"].tolist(), normalize_embeddings=True)\n'
                             'sim = cosine_similarity(vecs)'},
                    {'language': 'Stata',
                     'title': 'Stata sketch',
                     'code': '* Compute embeddings outside Stata and merge the vectors back.\n'
                             'shell python embed.py --in corpus.csv --out vectors.csv\n'
                             'import delimited using vectors.csv, clear'}],
  'source_status': 'curated_scaffold',
  'name_zh': '词/文本嵌入',
  'description_zh': '将词、文档或实体表示为稠密向量，其几何结构编码相似性。',
  'seminal_works': []},
 {'id': 'computational-content-analysis',
  'name': 'Computational Content Analysis',
  'category': 'computational',
  'sub_category': 'Text Analysis',
  'difficulty': 'Intermediate',
  'description': 'Applies dictionaries or rules at scale to measure theoretically defined '
                 'categories in text.',
  'tags': ['computational content analysis', 'automated content analysis', 'dictionary analysis'],
  'broad_tags': ['text_mining', 'nlp'],
  'use_when': ['The construct maps to identifiable lexical markers.',
               'You need a transparent, reproducible measure across a large corpus.'],
  'assumptions': ['The dictionary covers the construct in this corpus’s language use',
                  'Terms carry consistent meaning across the corpus',
                  'Negation and context are handled or their omission is disclosed'],
  'workflow': ['Define the construct and derive the dictionary from it.',
               'Validate the dictionary on a hand-coded sample from this corpus.',
               'Report coverage and false-positive rates.',
               'Apply the dictionary with documented preprocessing.',
               'Report the dictionary in full so others can reuse it.'],
  'diagnostics': ['Precision and recall against hand coding',
                  'Coverage rate across documents',
                  'Sensitivity to dictionary variants',
                  'Manual audit of matched passages'],
  'pitfalls': ['Reusing an off-the-shelf dictionary built for another domain without revalidation.',
               'Counting term frequency without handling negation or quotation.',
               'Reporting a dictionary score as a validated construct measure without hand-coded '
               'evidence.'],
  'related_methods': ['content-analysis', 'text-classification', 'topic-modeling'],
  'code_examples': [{'language': 'R',
                     'title': 'R sketch',
                     'code': 'library(quanteda)\n'
                             'dict <- dictionary(list(uncertainty = c("uncertain*", "unclear", '
                             '"unpredictab*")))\n'
                             'res <- dfm(tokens(corpus(df$text)), dictionary = dict)\n'
                             'convert(res, to = "data.frame")\n'
                             'kwic(tokens(corpus(df$text)), pattern = "uncertain*")'},
                    {'language': 'Python',
                     'title': 'Python sketch',
                     'code': 'import re\n'
                             '\n'
                             'terms = [r"uncertain\\w*", r"unclear", r"unpredictab\\w*"]\n'
                             'pat = re.compile("|".join(terms), re.I)\n'
                             'df["uncertainty"] = df["text"].str.count(pat)\n'
                             'print(df.loc[df.uncertainty > 0, "text"].sample(20).tolist())'},
                    {'language': 'Stata',
                     'title': 'Stata sketch',
                     'code': '* Count dictionary hits, then audit the matched passages by hand.\n'
                             'gen lower_text = lower(text)\n'
                             'gen uncertainty = strpos(lower_text, "uncertain") > 0 ///\n'
                             '               | strpos(lower_text, "unclear") > 0 ///\n'
                             '               | strpos(lower_text, "unpredictab") > 0\n'
                             'tabulate uncertainty\n'
                             'list text if uncertainty == 1 in 1/20'}],
  'source_status': 'curated_scaffold',
  'name_zh': '计算内容分析',
  'description_zh': '大规模应用词典或规则，测量理论上界定的类别。',
  'seminal_works': []},
 {'id': 'network-analysis',
  'name': 'Network Analysis',
  'category': 'computational',
  'sub_category': 'Relational Data',
  'difficulty': 'Intermediate',
  'description': 'Analyses the structure of relationships among nodes rather than attributes of '
                 'isolated units.',
  'tags': ['network analysis', 'network models', 'network model', 'social network analysis'],
  'broad_tags': [],
  'use_when': ['The unit of interest is a relationship, not an isolated observation.',
               'Structural position is theorized to matter.'],
  'assumptions': ['Network boundary is defined by a stated rule',
                  'Edges are measured consistently across the network',
                  'Missing ties are addressed rather than treated as absent ties'],
  'workflow': ['Define the node set and the boundary rule explicitly.',
               'Define what an edge represents and its direction and weight.',
               'Assess and report missing-tie coverage.',
               'Compute the structural measures the theory implies, not every available one.',
               'Compare observed structure with an appropriate null model.'],
  'diagnostics': ['Boundary sensitivity analysis',
                  'Missing-data assessment',
                  'Comparison against random or configuration null models',
                  'Robustness of centrality to edge removal'],
  'pitfalls': ['Treating unobserved ties as absent ties, which biases every centrality measure.',
               'Reporting many centrality measures and interpreting whichever correlates with the '
               'outcome.',
               'Running standard regressions on network-derived variables without accounting for '
               'dependence.'],
  'related_methods': ['embeddings', 'agent-based-modeling', 'computational-content-analysis'],
  'code_examples': [{'language': 'R',
                     'title': 'R sketch',
                     'code': 'library(igraph)\n'
                             'g <- graph_from_data_frame(edges, directed = FALSE)\n'
                             'V(g)$btw <- betweenness(g, normalized = TRUE)\n'
                             'null <- sample_degseq(degree(g), method = "vl")\n'
                             'c(observed = transitivity(g), null = transitivity(null))'},
                    {'language': 'Python',
                     'title': 'Python sketch',
                     'code': 'import networkx as nx\n'
                             '\n'
                             'g = nx.from_pandas_edgelist(edges, "source", "target")\n'
                             'btw = nx.betweenness_centrality(g, normalized=True)\n'
                             'null = nx.configuration_model([d for _, d in g.degree()])\n'
                             'print(nx.transitivity(g), nx.transitivity(nx.Graph(null)))'},
                    {'language': 'Stata',
                     'title': 'Stata sketch',
                     'code': '* Export the edge list, compute in igraph/networkx, merge measures '
                             'back.\n'
                             'shell python network_measures.py --edges edges.csv --out '
                             'centrality.csv\n'
                             'import delimited using centrality.csv, clear'}],
  'source_status': 'curated_scaffold',
  'name_zh': '网络分析',
  'description_zh': '分析行动者之间的关系结构，而非孤立个体的属性。',
  'seminal_works': []},
 {'id': 'agent-based-modeling',
  'name': 'Agent-Based Modeling',
  'category': 'computational',
  'sub_category': 'Simulation',
  'difficulty': 'Advanced',
  'description': 'Simulates interacting agents following specified rules to study emergent '
                 'aggregate patterns.',
  'tags': ['agent-based modeling', 'agent based modeling', 'agent-based simulation'],
  'broad_tags': ['simulation'],
  'use_when': ['Aggregate outcomes emerge from local interaction rather than aggregation of '
               'averages.',
               'Analytical solutions are intractable.'],
  'assumptions': ['Agent rules are stated explicitly and justified',
                  'Results are robust to random seeds',
                  'Parameter ranges are defended rather than tuned to the desired result'],
  'workflow': ['Specify agents, states, rules, and the interaction topology.',
               'Document initial conditions and parameter ranges.',
               'Run many replications per parameter set with recorded seeds.',
               'Conduct a systematic sensitivity analysis over the parameter space.',
               'Validate emergent patterns against an external benchmark where one exists.',
               'Publish the model code and parameter files.'],
  'diagnostics': ['Seed-variation analysis',
                  'Parameter sweep and sensitivity',
                  'Convergence over replications',
                  'Docking against a known model or benchmark'],
  'pitfalls': ['Reporting one run per parameter set as if it were the model’s prediction.',
               'Tuning parameters until the target pattern emerges and calling that validation.',
               'Publishing results without the model code, making them unreproducible.'],
  'related_methods': ['network-analysis', 'experiment'],
  'code_examples': [{'language': 'R',
                     'title': 'R sketch',
                     'code': 'library(NetLogoR)\n'
                             'set.seed(42)\n'
                             'replicate(200, {\n'
                             '  # step the world, return the aggregate outcome\n'
                             '  simulate_world(n_agents = 500, threshold = 0.3)\n'
                             '})'},
                    {'language': 'Python',
                     'title': 'Python sketch',
                     'code': 'import numpy as np\n'
                             '\n'
                             'rng = np.random.default_rng(42)\n'
                             'results = [run_model(n_agents=500, threshold=t, rng=rng)\n'
                             '           for t in np.linspace(0.1, 0.9, 17)\n'
                             '           for _ in range(200)]'},
                    {'language': 'Stata',
                     'title': 'Stata sketch',
                     'code': '* Run the simulation externally and analyse the sweep output in '
                             'Stata.\n'
                             'shell python abm_sweep.py --reps 200 --out sweep.csv\n'
                             'import delimited using sweep.csv, clear\n'
                             'table threshold, statistic(mean outcome) statistic(sd outcome)'}],
  'source_status': 'curated_scaffold',
  'name_zh': '基于主体的建模',
  'description_zh': '模拟遵循设定规则的主体互动，研究涌现的宏观模式。',
  'seminal_works': []},
 {'id': 'web-scraping',
  'name': 'Web Scraping',
  'category': 'computational',
  'sub_category': 'Data Collection',
  'difficulty': 'Intermediate',
  'description': 'Programmatically collects structured data from web sources for research use.',
  'tags': ['web scraping', 'web crawling', 'data scraping'],
  'broad_tags': [],
  'use_when': ['The data exist publicly but no API or dataset provides them.',
               'The collection can be documented and repeated.'],
  'assumptions': ['Collection complies with terms of service, robots directives, and applicable '
                  'law',
                  'The sample frame is defined rather than being whatever was reachable',
                  'Page structure is stable enough over the collection window'],
  'workflow': ['Check the terms of service, robots.txt, and any API alternative first.',
               'Define the sampling frame and the collection window in advance.',
               'Rate-limit requests and identify the crawler.',
               'Store raw responses alongside the parsed output.',
               'Log failures and coverage so gaps are visible.',
               'Record a data provenance note with dates and source URLs.'],
  'diagnostics': ['Coverage and failure-rate logs',
                  'Parser validation on a manual sample',
                  'Re-collection stability checks',
                  'Duplicate detection'],
  'pitfalls': ['Treating whatever was successfully scraped as a random sample.',
               'Discarding raw responses, making parsing errors impossible to audit later.',
               'Ignoring rate limits, terms of service, or personal-data obligations.'],
  'related_methods': ['computational-content-analysis', 'text-classification'],
  'code_examples': [{'language': 'R',
                     'title': 'R sketch',
                     'code': 'library(httr2); library(rvest)\n'
                             'resp <- request(url) |> req_user_agent("research-bot '
                             '(contact@example.edu)") |>\n'
                             '  req_throttle(rate = 30 / 60) |> req_perform()\n'
                             'writeLines(resp_body_string(resp), "raw/page_001.html")\n'
                             'page <- read_html("raw/page_001.html") |> html_elements(".item") |> '
                             'html_text2()'},
                    {'language': 'Python',
                     'title': 'Python sketch',
                     'code': 'import time, pathlib, requests\n'
                             'from bs4 import BeautifulSoup\n'
                             '\n'
                             'headers = {"User-Agent": "research-bot (contact@example.edu)"}\n'
                             'r = requests.get(url, headers=headers, timeout=30)\n'
                             'pathlib.Path("raw/page_001.html").write_text(r.text, '
                             'encoding="utf-8")\n'
                             'items = [e.get_text(strip=True) for e in BeautifulSoup(r.text, '
                             '"html.parser").select(".item")]\n'
                             'time.sleep(2)'},
                    {'language': 'Stata',
                     'title': 'Stata sketch',
                     'code': '* Collect outside Stata, keep the raw payloads, import the parsed '
                             'table.\n'
                             'shell python scrape.py --frame frame.csv --raw raw/ --out '
                             'parsed.csv\n'
                             'import delimited using parsed.csv, clear'}],
  'source_status': 'curated_scaffold',
  'name_zh': '网页抓取',
  'description_zh': '以程序方式从网络来源采集结构化数据用于研究。',
  'seminal_works': []},
 {'id': 'interviews',
  'name': 'Qualitative Interviews',
  'category': 'qualitative',
  'sub_category': 'Data Collection',
  'difficulty': 'Intermediate',
  'description': 'Generates detailed accounts of experience and meaning through semi-structured '
                 'conversation.',
  'tags': ['qualitative_interviews',
           'qualitative interviews',
           'interviews',
           'interview',
           'semi-structured interviews',
           'in-depth interviews'],
  'broad_tags': [],
  'use_when': ['You need participants’ own framing rather than pre-set response options.',
               'The phenomenon is not well enough understood to specify a survey.'],
  'assumptions': ['Participants can speak to the phenomenon',
                  'Sampling is purposive and its logic is stated',
                  'The researcher’s position is reflected on rather than assumed neutral'],
  'workflow': ['Define the research question and the sampling logic.',
               'Draft and pilot the interview guide.',
               'Obtain informed consent and agree recording and anonymity terms.',
               'Conduct interviews, writing memos immediately after each.',
               'Transcribe and anonymize systematically.',
               'Continue until additional interviews stop changing the analysis, and report that '
               'judgement.'],
  'diagnostics': ['Sampling-logic documentation',
                  'Memo trail',
                  'Member checking where appropriate',
                  'Transparency about saturation reasoning'],
  'pitfalls': ['Reporting a sample size as "saturation" without describing how it was judged.',
               'Quoting selectively to support a preferred reading without showing disconfirming '
               'accounts.',
               'Treating interview accounts as direct evidence of behaviour rather than of '
               'accounts.'],
  'related_methods': ['thematic-analysis', 'grounded-theory', 'case-study', 'ethnography'],
  'code_examples': [],
  'source_status': 'curated_scaffold',
  'name_zh': '质性访谈',
  'description_zh': '通过半结构化对话获得关于经验与意义的详细叙述。',
  'seminal_works': []},
 {'id': 'thematic-analysis',
  'name': 'Thematic Analysis',
  'category': 'qualitative',
  'sub_category': 'Qualitative Coding',
  'difficulty': 'Intermediate',
  'description': 'Identifies, analyses, and reports patterns of meaning across a qualitative '
                 'dataset.',
  'tags': ['thematic analysis', 'thematic coding'],
  'broad_tags': ['qualitative_interviews'],
  'use_when': ['You want patterned meaning across cases rather than a single case narrative.',
               'The analysis is interpretive rather than frequency counting.'],
  'assumptions': ['The analytic approach (inductive or deductive) is stated',
                  'Coding decisions are documented and auditable',
                  'Themes are developed rather than merely summarizing topics'],
  'workflow': ['State the epistemological stance and whether coding is inductive or deductive.',
               'Read the corpus for familiarization before coding.',
               'Generate initial codes systematically across the whole dataset.',
               'Collate codes into candidate themes.',
               'Review themes against coded extracts and the full dataset.',
               'Define, name, and illustrate each theme with representative extracts.'],
  'diagnostics': ['Audit trail of coding decisions',
                  'Second-coder review or team discussion',
                  'Negative-case analysis',
                  'Extract-to-theme traceability'],
  'pitfalls': ['Presenting topic summaries as themes without an analytic point.',
               'Reporting an inter-rater kappa as if it validated an interpretive analysis.',
               'Showing only confirming extracts and omitting disconfirming ones.'],
  'related_methods': ['interviews', 'grounded-theory', 'content-analysis', 'case-study'],
  'code_examples': [],
  'source_status': 'curated_scaffold',
  'name_zh': '主题分析',
  'description_zh': '在质性数据集中识别、分析并报告意义的模式。',
  'seminal_works': []},
 {'id': 'grounded-theory',
  'name': 'Grounded Theory',
  'category': 'qualitative',
  'sub_category': 'Theory Building',
  'difficulty': 'Advanced',
  'description': 'Builds theory from data through iterative coding, constant comparison, and '
                 'theoretical sampling.',
  'tags': ['grounded theory', 'grounded theory approach'],
  'broad_tags': ['qualitative_interviews'],
  'use_when': ['No adequate theory exists for the phenomenon.',
               'The contribution is a new conceptual account rather than a test.'],
  'assumptions': ['Data collection and analysis proceed iteratively rather than sequentially',
                  'Sampling follows emerging concepts',
                  'Constant comparison is applied throughout'],
  'workflow': ['Enter the field with a research question rather than a hypothesis set.',
               'Code openly, line by line, in the first pass.',
               'Write memos continuously and treat them as analysis.',
               'Sample theoretically based on emerging categories.',
               'Develop axial or focused codes linking categories.',
               'Continue until categories are saturated, and describe how that was judged.'],
  'diagnostics': ['Memo trail',
                  'Theoretical sampling log',
                  'Constant-comparison documentation',
                  'Category saturation account'],
  'pitfalls': ['Collecting all data first and then coding, which forecloses theoretical sampling.',
               'Labelling any inductive qualitative study "grounded theory" without its '
               'procedures.',
               'Presenting a category list as a theory without stating relationships among '
               'categories.'],
  'related_methods': ['interviews', 'thematic-analysis', 'case-study', 'ethnography'],
  'code_examples': [],
  'source_status': 'curated_scaffold',
  'name_zh': '扎根理论',
  'description_zh': '通过迭代编码、持续比较与理论抽样从数据中建构理论。',
  'seminal_works': []},
 {'id': 'case-study',
  'name': 'Case Study',
  'category': 'qualitative',
  'sub_category': 'Research Design',
  'difficulty': 'Intermediate',
  'description': 'Investigates a phenomenon in depth within its real-world context, often across '
                 'multiple data sources.',
  'tags': ['case study',
           'comparative case study',
           'qualitative case study',
           'multi-case study',
           'single-case study',
           'historical case study'],
  'broad_tags': [],
  'use_when': ['Context is inseparable from the phenomenon.',
               'The question is how or why something unfolded.'],
  'assumptions': ['Case selection follows a stated logic, not convenience alone',
                  'Case boundaries are defined explicitly',
                  'Evidence is triangulated across sources'],
  'workflow': ['Define the case and its boundaries.',
               'State the selection logic: typical, extreme, critical, or theoretically sampled.',
               'Collect data from multiple sources and maintain a case database.',
               'Build a within-case account before comparing cases.',
               'Conduct cross-case comparison where multiple cases exist.',
               'Maintain a chain of evidence from question to conclusion.'],
  'diagnostics': ['Case database and chain of evidence',
                  'Source triangulation',
                  'Rival-explanation assessment',
                  'Within-case before cross-case discipline'],
  'pitfalls': ['Selecting cases on the outcome and inferring what caused it.',
               'Generalizing statistically from a small purposive set of cases.',
               'Presenting a single narrative without addressing rival explanations.'],
  'related_methods': ['interviews', 'grounded-theory', 'thematic-analysis', 'ethnography'],
  'code_examples': [],
  'source_status': 'curated_scaffold',
  'name_zh': '案例研究',
  'description_zh': '在真实情境中深入考察某一现象，通常整合多源数据。',
  'seminal_works': []},
 {'id': 'content-analysis',
  'name': 'Content Analysis',
  'category': 'qualitative',
  'sub_category': 'Qualitative Coding',
  'difficulty': 'Introductory',
  'description': 'Systematically codes documents or media against a defined scheme, with explicit '
                 'reliability checks.',
  'tags': ['content analysis', 'qualitative content analysis'],
  'broad_tags': [],
  'use_when': ['The material is textual or visual and the categories can be specified.',
               'You need a systematic, replicable coding of a defined corpus.'],
  'assumptions': ['The coding scheme is defined before full coding',
                  'Coders are trained and reliability is measured',
                  'The sampling frame for documents is stated'],
  'workflow': ['Define the corpus and the sampling frame.',
               'Develop the codebook with explicit inclusion and exclusion rules.',
               'Train coders and pilot on a subset.',
               'Measure inter-coder reliability on an independent subsample.',
               'Code the full corpus, resolving disagreements by a stated rule.',
               'Report reliability per category, not only overall.'],
  'diagnostics': ['Krippendorff’s alpha or Cohen’s kappa per category',
                  'Codebook version control',
                  'Coder drift checks over time',
                  'Double-coded subsample size'],
  'pitfalls': ['Reporting one overall reliability figure that hides unreliable individual '
               'categories.',
               'Revising the codebook mid-coding without recoding earlier material.',
               'Treating frequency counts as evidence of importance.'],
  'related_methods': ['computational-content-analysis', 'thematic-analysis', 'text-classification'],
  'code_examples': [],
  'source_status': 'curated_scaffold',
  'name_zh': '内容分析',
  'description_zh': '依据明确编码方案系统地对文档或媒介进行编码，并检验信度。',
  'seminal_works': []},
 {'id': 'ethnography',
  'name': 'Ethnography',
  'category': 'qualitative',
  'sub_category': 'Field Research',
  'difficulty': 'Advanced',
  'description': 'Studies practices and meanings through sustained participation in a setting.',
  'tags': ['ethnography', 'ethnographic', 'ethnographic fieldwork', 'participant observation'],
  'broad_tags': [],
  'use_when': ['Practices are tacit and not reliably reported in interviews.',
               'Understanding requires prolonged presence in the setting.'],
  'assumptions': ['Sustained access to the setting',
                  'Field relations and researcher positionality are reflected on',
                  'Observation is recorded systematically rather than recalled later'],
  'workflow': ['Negotiate access and agree ethical terms with the setting.',
               'Establish an observation schedule covering varied times and situations.',
               'Write field notes promptly and separate description from interpretation.',
               'Combine observation with informal and formal interviews.',
               'Analyse iteratively during fieldwork, not only afterwards.',
               'Reflect on positionality and its effect on what was observable.'],
  'diagnostics': ['Field-note discipline and timing',
                  'Observation coverage across situations',
                  'Positionality statement',
                  'Triangulation with interview and document data'],
  'pitfalls': ['Presenting interpretation as description without separating the two in field '
               'notes.',
               'Overclaiming from a short visit and calling it ethnography.',
               'Omitting how the researcher’s presence changed the setting.'],
  'related_methods': ['interviews', 'case-study', 'grounded-theory', 'thematic-analysis'],
  'code_examples': [],
  'source_status': 'curated_scaffold',
  'name_zh': '民族志',
  'description_zh': '通过在场域中的长期参与来研究实践与意义。',
  'seminal_works': []}]
