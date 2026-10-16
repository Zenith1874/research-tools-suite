# -*- coding: utf-8 -*-
"""Deep dive for attachment theory.

Added because the catalog had no attachment entry at all, despite the theory
carrying two large and largely separate business literatures: adult attachment
style at work in OB, and emotional brand attachment in marketing. It is the
clearest case in the catalog of one theory with two home disciplines.

Schema helpers live in ``research_catalog_deep_dives``.
"""

from research_catalog_deep_dives import D, Debate, P, Pos

THEORY_DIVES_B16 = dict([

    D('attachment-theory',
      era='Developed in developmental psychology from 1969; carried into adult relationships in 1987 and into consumer and organizational research from the 1990s.',
      era_zh='1969 年起在发展心理学中形成，1987 年被引入成人关系研究，1990 年代起进入消费者与组织研究。',
      situation=[
        P('Accounts of the infant-caregiver bond explained it as learned association with feeding, which could not explain why distressed infants seek proximity to a caregiver who does not feed them and resist separation even when their needs are otherwise met.',
          '关于婴儿—照料者纽带的解释此前把它归为与喂食相联结的习得反应；这无法说明为何处于痛苦中的婴儿会寻求接近并不喂养他们的照料者，且在其他需要都被满足时仍抗拒分离。'),
        P('The alternative was a behavioural system selected for protection rather than for feeding, which made the bond primary rather than derived and opened the question of what happens when it is unreliable.',
          '替代解释是一个为获得保护而非获得喂食所选择出来的行为系统；这使该纽带成为原初的而非派生的，并提出了"当它不可靠时会怎样"的问题。'),
      ],
      argument=[
        P('An attachment system regulates proximity to a figure who serves as a safe haven under threat and a secure base for exploration when threat recedes. The two functions are distinct and a figure can supply one without the other.',
          '依恋系统调节个体与依恋对象之间的接近程度：该对象在威胁下充当安全港，在威胁消退时充当探索的安全基地。两种功能彼此不同，某一对象可能只提供其中之一。'),
        P('Repeated experience of whether the figure is available and responsive is encoded as an internal working model, which carries forward and shapes expectations in later relationships the figure has nothing to do with.',
          '关于依恋对象是否可得、是否回应的反复经验被编码为内部工作模型；它会延续下去，塑造个体在与该对象无关的后续关系中的预期。'),
        P('Individual differences are described by two dimensions rather than types: anxiety, meaning fear of unavailability, and avoidance, meaning discomfort with dependence. Security is low on both, and the two predict different behaviour rather than more or less of the same thing.',
          '个体差异以两个维度而非类型来刻画：焦虑，即对依恋对象不可得的恐惧；回避，即对依赖的不适。安全型在两个维度上都低；二者预测的是不同行为，而非同一事物的多寡。'),
      ],
      development=[
        P('The theory was extended from infants to adult romantic bonds, then to workplace relationships with leaders and organizations, and separately to consumers relationships with brands, where the same two dimensions were applied to an object that cannot reciprocate.',
          '该理论从婴儿扩展到成人恋爱关系，继而扩展到与领导者及组织的职场关系；另一条线索则扩展到消费者与品牌的关系——在那里同样的两个维度被应用于一个无法回应的对象。'),
      ],
      debates=[
        Debate('Can a brand or an organization be an attachment figure?', '品牌或组织能成为依恋对象吗？',
               [Pos('Extension position',
                    'Emotional brand attachment predicts separation distress, willingness to sacrifice, and resistance to negative information, which is the behavioural signature the theory specifies.',
                    '情感性品牌依恋能预测分离痛苦、愿意付出代价，以及对负面信息的抵抗——这正是理论所规定的行为特征。'),
                Pos('Dilution critique',
                    'The theory rests on a figure who can respond, protect and be sought out under threat. A brand does none of these, so what is measured may be strong preference relabelled with attachment vocabulary.',
                    '该理论依赖于一个能够回应、保护、并在威胁下可被求助的对象。品牌不具备任何一项；因此所测量的可能只是被冠以依恋词汇的强烈偏好。')],
               'Unresolved and consequential: it decides whether the brand literature inherits the theory predictions about threat and separation, or only borrows its language.',
               '未决且后果重大：它决定了品牌文献究竟继承了该理论关于威胁与分离的预测，还是仅仅借用了它的语言。'),
      ],
      theoretical=[
        P('The internal working model is the mechanism carrying childhood experience into adult relationships, and it is not observed directly in any business study; it is inferred from the adult self-report it is meant to explain.',
          '内部工作模型是把童年经验带入成人关系的机制，而在任何商科研究中它都未被直接观察；它是从其本应解释的成人自评中推断出来的。'),
        P('Attachment style is described as stable enough to transfer across relationships yet responsive enough to be shaped by a particular leader or brand, and the theory does not specify how much of each, which lets almost any result be accommodated.',
          '依恋风格被描述为既稳定到足以跨关系迁移，又敏感到能被特定领导者或品牌塑造；理论未规定两者各占多少，这使几乎任何结果都能被容纳。'),
      ],
      empirical=[
        P('Adult attachment is measured by self-report about close relationships and then used to predict workplace or consumption outcomes, so the predictor and the outcome come from the same person and the same instrument in most designs.',
          '成人依恋以关于亲密关系的自评测量，随后被用来预测职场或消费结果；因此在多数设计中，预测变量与结果来自同一个人、同一份工具。'),
        P('The dimensional structure was validated on romantic relationships, and the brand and organizational adaptations reuse the item wording with the target swapped, which is rarely revalidated for the new target.',
          '维度结构是在恋爱关系上验证的；品牌与组织版本沿用题项措辞、仅替换对象，而很少针对新对象重新验证。'),
      ],
      temporal=[
        P('The theory assumes an attachment figure who is encountered repeatedly and can be sought out when threatened, which is what makes availability informative. Where the relationship is with an organization the employee meets through scheduled remote contact, or with a brand encountered through an interface, there is no figure whose responsiveness under threat can be tested, and the working model is being formed from something that cannot fail to respond in the way the theory describes.',
          '该理论假定依恋对象会被反复遇到、并可在受威胁时被求助——这正是"可得性"具有信息量的原因。当关系的对象是员工只通过预定远程接触遇到的组织、或通过界面遇到的品牌时，不存在其"威胁下的回应性"可被检验的对象；工作模型所依据的东西，无法以理论所描述的方式失败。'),
        P('Adult attachment research was built where a person had few close relationships and each was costly to replace, which is what gives separation its force. Where connections are numerous, partial and cheap to substitute, the anxiety dimension refers to a loss that is less consequential than the instrument assumes, and scores are not comparable to the samples the scales were normed on.',
          '成人依恋研究建立在"个体亲密关系不多、且每一段都难以替代"的前提上——这正是分离具有冲击力的原因。当联系众多、局部且易于替换时，焦虑维度所指的丧失，其后果低于工具的假定；分数也无法与量表常模所依据的样本相比较。'),
      ],
      today=[
        P('State which target the attachment is to, and revalidate the instrument for that target rather than swapping the referent in items written about romantic partners.',
          '应说明依恋的对象是谁，并针对该对象重新验证工具，而非在为恋爱伴侣撰写的题项中替换指称对象。'),
        P('Report the two dimensions separately. Collapsing them into a secure-versus-insecure split discards the distinction that does the predictive work, since anxiety and avoidance predict opposite behaviour under the same threat.',
          '应分别报告两个维度。把它们压缩为"安全对不安全"的二分，会丢弃真正承担预测作用的区分——在同样的威胁下，焦虑与回避预测相反的行为。'),
      ]),
])
