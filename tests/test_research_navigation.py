# -*- coding: utf-8 -*-
"""全站研究导航的静态契约测试。"""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'static'
PRIMARY_PAGES = (
    'index.html',
    'dashboard.html',
    'fiscal_debt.html',
    'china_rates.html',
    'city_economy.html',
    'housing_scenario.html',
    'housing.html',
    'us_macro.html',
    'gdp.html',
    'debt_ceiling.html',
    'abdc/index.html',
    'abdc_astar_research.html',
    'paper_translation.html',
    'audio_transcription.html',
    'audio_transcription_result.html',
    'yuedu_fm.html',
    'cardcookie_monitor.html',
)


class ResearchNavigationContractTests(unittest.TestCase):
    def test_primary_pages_load_shared_navigation(self):
        missing = []
        for relative_path in PRIMARY_PAGES:
            html = (STATIC / relative_path).read_text(encoding='utf-8')
            if '/research-nav.css' not in html or '/research-nav.js' not in html:
                missing.append(relative_path)
        self.assertEqual(missing, [], f'以下页面未接入共享导航: {missing}')

    def test_navigation_has_five_primary_groups(self):
        script = (STATIC / 'research-nav.js').read_text(encoding='utf-8')
        group_block = script.split('const groups = {', 1)[1].split('};', 1)[0]
        self.assertEqual(group_block.count("label: '中国宏观'"), 1)
        self.assertEqual(group_block.count("label: '美国宏观'"), 1)
        self.assertEqual(group_block.count("label: 'ABDC 商科研究'"), 1)
        self.assertEqual(group_block.count("label: '科研工具'"), 1)
        self.assertEqual(group_block.count("label: '娱乐'"), 1)

    def test_language_workbench_is_separate_from_abdc_research(self):
        script = (STATIC / 'research-nav.js').read_text(encoding='utf-8')
        research_block = script.split('research: {', 1)[1].split('tools: {', 1)[0]
        tools_block = script.split('tools: {', 1)[1].split('\n    }\n  };', 1)[0]
        self.assertNotIn('/paper-translation', research_block)
        self.assertIn("label: '学术语言工作台'", tools_block)
        self.assertIn("href: '/paper-translation'", tools_block)
        self.assertIn("label: '研究语音工作台'", tools_block)
        self.assertIn("href: '/audio-transcription'", tools_block)
        self.assertIn("if (/^\\/(paper-translation|audio-transcription)/.test(pathname)) return 'tools';", script)

    def test_existing_routes_are_present_in_navigation(self):
        script = (STATIC / 'research-nav.js').read_text(encoding='utf-8')
        for route in ('/dashboard', '/fiscal-debt', '/china-rates', '/city-economy',
                      '/housing', '/housing-scenario',
                      '/us-macro', '/gdp', '/abdc', '/abdc-astar-research'):
            self.assertIn(f"href: '{route}'", script)
        self.assertIn("href: '/paper-translation'", script)
        self.assertIn("href: '/audio-transcription'", script)
        self.assertIn("href: '/yuedu-fm'", script)
        self.assertIn("href: '/cardcookie-monitor'", script)

    def test_china_navigation_labels_are_compact_and_homepage_is_complete(self):
        navigation = (STATIC / 'research-nav.js').read_text(encoding='utf-8')
        homepage = (STATIC / 'index.html').read_text(encoding='utf-8')
        stylesheet = (STATIC / 'research-nav.css').read_text(encoding='utf-8')
        self.assertIn("summary: '实体 · 金融 · 财政 · 城市'", navigation)
        self.assertIn("label: '货币信用', href: '/dashboard'", navigation)
        self.assertNotIn("label: '宏观总览', href: '/dashboard'", navigation)
        self.assertIn('<span class="domain-count">10 个研究模块</span>', homepage)
        for route in ('/dashboard', '/china-macro', '/macro-analytics', '/gdp',
                      '/housing', '/fiscal-debt', '/debt-ceiling', '/china-rates',
                      '/city-economy', '/housing-scenario'):
            self.assertIn(f'href="{route}"', homepage)
        self.assertIn('overflow: hidden;', stylesheet)
        self.assertIn('text-overflow: ellipsis;', stylesheet)

    def test_homepage_lists_both_research_utilities(self):
        homepage = (STATIC / 'index.html').read_text(encoding='utf-8')
        self.assertIn('<span class="domain-count">2 个可用工具</span>', homepage)
        self.assertIn('href="/paper-translation"', homepage)
        self.assertIn('href="/audio-transcription"', homepage)
        self.assertIn('href="/yuedu-fm"', homepage)
        self.assertIn('href="/cardcookie-monitor"', homepage)
        self.assertNotIn('语音功能规划中', homepage)

    def test_audio_workbench_prefers_new_result_page_over_download(self):
        workbench = (STATIC / 'audio_transcription.html').read_text(encoding='utf-8')
        result_page = (STATIC / 'audio_transcription_result.html').read_text(encoding='utf-8')
        self.assertIn("window.open('about:blank','_blank')", workbench)
        self.assertIn('打开查看结果', workbench)
        self.assertIn('target="_blank" rel="noopener"', workbench)
        self.assertIn("'/api/audio/jobs/'+jobId+'/result'", result_page)
        self.assertIn('直接查看是主要入口', result_page)
        self.assertIn('转录和说话人区分在 Keller 完成', workbench)
        self.assertIn('Iverson 上的 Qwen', workbench)
        self.assertIn('Keller 已连接 · GPU 空闲', workbench)
        self.assertIn('Iverson Qwen 已连接', workbench)

    def test_translation_page_does_not_fallback_to_excluded_hosts(self):
        page = (STATIC / 'paper_translation.html').read_text(encoding='utf-8')
        self.assertIn('Qwen 固定使用 Iverson', page)
        self.assertIn('不会回退到 simurgh 或 kaiju', page)

    def test_translation_page_defaults_to_translation_and_summary(self):
        page = (STATIC / 'paper_translation.html').read_text(encoding='utf-8')
        self.assertIn('<option value="translate_summarize" selected>', page)
        self.assertIn('id="preserve-references" type="checkbox" checked', page)

    def test_personal_research_fields_have_landing_filters(self):
        navigation = (STATIC / 'research-nav.js').read_text(encoding='utf-8')
        radar = (STATIC / 'abdc_astar_research.html').read_text(encoding='utf-8')
        for slug in ('information-systems', 'management', 'marketing', 'ob-hr',
                     'computational-social-science'):
            self.assertIn(slug, navigation)
            self.assertIn(slug, radar)

    def test_shared_navigation_exposes_access_mode(self):
        navigation = (STATIC / 'research-nav.js').read_text(encoding='utf-8')
        self.assertIn("fetch('/api/health'", navigation)
        self.assertIn('局域网只读', navigation)
        self.assertIn('本机管理', navigation)
        self.assertIn('protectReadOnlyControls', navigation)
        self.assertIn('MutationObserver', navigation)


if __name__ == '__main__':
    unittest.main()
