"""Continuity behaviors; synthetic fixtures contain no owner data."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import development_memory as dm

class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / '.project-master').mkdir()
        dm.enable(self.root, True)
    def tearDown(self):
        self.tmp.cleanup()
    def source(self, id='architecture', kind='architecture', text='Payment service preserves invoice identity'):
        path = self.root / (id + '.md')
        path.write_text(text)
        dm.register(self.root, id, path.name, kind, text)
        return path
    def test_changed_source_is_stale_and_not_retrieved(self):
        path = self.source()
        dm.index(self.root)
        self.assertTrue(dm.search(self.root, 'invoice')['results'])
        path.write_text('Changed contract')
        self.assertFalse(dm.search(self.root, 'invoice')['results'])
        self.assertIn('architecture', dm.context(self.root, {}, 3000)['stale'])
    def test_archive_keeps_negative_lesson_and_excludes_body(self):
        self.source('attempt', 'experiment', 'Rejected queue duplicates payments')
        with self.assertRaises(ValueError): dm.archive(self.root, 'attempt', 'Avoid duplicate delivery')
        dm.close(self.root, 'attempt', 'failed')
        dm.archive(self.root, 'attempt', 'Avoid duplicate delivery')
        dm.index(self.root)
        self.assertFalse(dm.search(self.root, 'duplicates')['results'])
        self.assertTrue(dm.search(self.root, 'duplicates', include_archive=True)['results'])
        self.assertIn('Avoid duplicate delivery', json.dumps(dm.context(self.root, {}, 3000)))
    def test_cannot_archive_test(self):
        self.source('regression', 'test')
        with self.assertRaises(ValueError): dm.close(self.root, 'regression', 'failed')
    def test_mandatory_overflow_is_visible(self):
        core = {'goal': 'goal ' * 400, 'blockers': ['do not lose me']}
        result = dm.context(self.root, core, 10)
        self.assertEqual(result['core'], core)
        self.assertTrue(result['budget_exceeded'])
    def test_corrupt_index_falls_back(self):
        self.source()
        dm.db_path(self.root).write_text('broken')
        result = dm.search(self.root, 'invoice')
        self.assertTrue(result['results'])
        self.assertEqual(result['mode'], 'files')
    def test_graph_is_bounded_and_has_provenance(self):
        self.source('a'); self.source('b')
        dm.link(self.root, 'a', 'b', 'depends_on', 'a.md')
        self.assertEqual(dm.neighbors(self.root, 'a', 1)[0]['target'], 'b')
        with self.assertRaises(ValueError): dm.link(self.root, 'a', 'missing', 'depends_on', 'a.md')
    def test_path_escape_rejected(self):
        with self.assertRaises(ValueError): dm.register(self.root, 'bad', '../secret', 'decision', 'bad')
    def test_checkpoint_detects_changed_work(self):
        p = self.source()
        dm.checkpoint(self.root)
        p.write_text('changed')
        self.assertIn('architecture', dm.context(self.root, {}, 3000)['stale'])

    def test_superseded_decision_is_not_retrieved(self):
        self.source('old', 'decision', 'Legacy database sqlite')
        self.source('new', 'decision', 'Current database postgres')
        dm.link(self.root, 'new', 'old', 'supersedes', 'new.md')
        dm.index(self.root)
        self.assertFalse(dm.search(self.root, 'Legacy')['results'])
        self.assertNotIn('old', [v['id'] for v in dm.context(self.root, {}, 3000)['summaries']])
    def test_untracked_edit_detected(self):
        subprocess.run(['git', 'init'], cwd=self.root, check=True, capture_output=True)
        path = self.source()
        before = dm.git_snapshot(self.root)
        path.write_text('new untracked content')
        self.assertNotEqual(before, dm.git_snapshot(self.root))
    def test_unchanged_chunks_reuse_embeddings(self):
        path = self.source(text='stable paragraph\n\nchanged paragraph')
        with patch('local_embeddings.embed', side_effect=lambda parts: [[1.0] * 384 for _ in parts]) as embed:
            dm.index(self.root, semantic=True)
            path.write_text('stable paragraph\n\nnew paragraph')
            dm.register(self.root, 'architecture', path.name, 'architecture', 'updated architecture')
            dm.index(self.root, semantic=True)
            self.assertEqual(embed.call_args.args[0], ['new paragraph'])
    def test_compact_context_is_smaller_than_full_sources(self):
        for n in range(12):
            path = self.root / ('component%d.md' % n)
            path.write_text(('Implementation detail for component %d. ' % n) * 300)
            dm.register(self.root, 'c%d' % n, path.name, 'component', 'Component %d contract summary' % n)
        full = {p.name: p.read_text() for p in self.root.glob('component*.md')}
        result = dm.context(self.root, {'goal': 'Deliver app', 'next_action': 'Verify current component'}, 3000)
        self.assertLess(dm.tokens(result), dm.tokens(full))
        self.assertEqual(result['core']['next_action'], 'Verify current component')
    def test_handoff_survives_small_budget(self):
        self.source('handoff', 'handoff', 'Continue unfinished migration with regression check')
        result = dm.context(self.root, {'goal': 'Keep working'}, 1)
        self.assertEqual(result['summaries'][0]['id'], 'handoff')
        self.assertTrue(result['budget_exceeded'])
    def test_incremental_index(self):
        self.source()
        self.assertEqual(dm.index(self.root)['updated_sources'], 1)
        self.assertEqual(dm.index(self.root)['updated_sources'], 0)
    def test_active_evidence_protected(self):
        self.source('a', 'decision'); self.source('b', 'experiment')
        dm.link(self.root, 'a', 'b', 'depends_on', 'b.md')
        dm.close(self.root, 'b', 'failed')
        with self.assertRaises(ValueError): dm.archive(self.root, 'b', 'lesson')
    def test_recovery_preserves_goal_and_next_step(self):
        import init_project, recover
        with tempfile.TemporaryDirectory() as path:
            root = Path(path)
            init_project.initialize(root, 'Synthetic', 'Build invoice application', 'STANDARD', False)
            expected = recover.recover(root)
            dm.enable(root, True)
            self.assertEqual(recover.recover(root), expected)
            actual = recover.recover(root, 10, compact=True)
            self.assertEqual(actual['core']['mission'], expected['mission'])
            self.assertEqual(actual['core']['next_action'], expected['next_action'])
            self.assertTrue(actual['budget_exceeded'])
    def test_dirty_content_change_detected(self):
        def git(*args): subprocess.run(['git', *args], cwd=self.root, check=True, capture_output=True)
        git('init'); git('config', 'user.name', 'Synthetic'); git('config', 'user.email', 'test@example.invalid')
        path = self.source()
        git('add', 'architecture.md'); git('commit', '-m', 'fixture')
        path.write_text('first edit'); before = dm.git_snapshot(self.root)
        path.write_text('second edit'); after = dm.git_snapshot(self.root)
        self.assertNotEqual(before['diff_hash'], after['diff_hash'])
    @unittest.skipUnless(os.environ.get('PM_EMBEDDING_TEST') == '1', 'optional local embedding runtime')
    def test_real_local_semantic_retrieval(self):
        self.source('payment', 'decision', 'Счета нельзя оплачивать повторно. Идемпотентность платежей.')
        self.source('visual', 'decision', 'Цвет кнопки выбирается в настройках интерфейса.')
        self.assertTrue(dm.index(self.root, semantic=True)['semantic'])
        result = dm.search(self.root, 'защита от двойного списания денег', semantic=True)
        self.assertEqual(result['mode'], 'hybrid')
        self.assertEqual(result['results'][0]['id'], 'payment')
        self.assertEqual(dm.index(self.root, semantic=True)['updated_sources'], 0)

if __name__ == '__main__': unittest.main()
