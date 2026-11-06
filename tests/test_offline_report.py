import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cecropis.offline_report import extract_report, render_report, export_report


def fixture():
    cfg = dict(steps=2, alpha=.3, rho=.9,
               input_events=[dict(body_ids=['1'], start=0, stop=1, amplitude=.6)],
               observations=[dict(name='O', body_ids=['2'], evaluation_window=dict(start=0, stop=2))],
               intervention_ids=['3'], gain=.2, intervention_start=0, intervention_stop=2)
    summary = dict(type='O', node_count=1, baseline_sum=.12345678901234568,
                   intervention_sum=.1, sum_delta=-.02345678901234568,
                   baseline_mean=.06172839450617284, intervention_mean=.05,
                   mean_delta=-.01172839450617284, relative_sum_delta=-.19,
                   baseline_near_zero=False, sample_count=2, evaluation_window=dict(start=0, stop=2))
    judgments = dict(name='=SUM(A1)', feasible=False,
                     target_constraint=dict(observation='O', metric='relative', minimum=.2, loss=.19, satisfied=False, defined=True),
                     protected_constraints=dict(O=dict(metric='absolute', limit=.001, loss=.01172839450617284, satisfied=False, defined=True)))
    task = dict(name='<img src=x onerror=alert(1)>', description='stored at F:\\private\\records',
                source_index_id='source-uuid', model_version='bounded-propagation-v1',
                scope=dict(body_ids=['1', '2', '3']),
                conditions=[dict(name='=SUM(A1)', experiment=cfg, role='decision', search_options=dict(target_output='O')),
                            dict(name='@not-run', experiment=cfg, role='extra')])
    return dict(case_id='local-scope', model_version='bounded-propagation-v1',
                actual_data_identity=dict(case_id='local-scope', source_index_id='local-uuid', scope_content=dict(internal_edges=2)),
                computation_node_count=3, task_definition=task, status='cancelled',
                conditions=[dict(name='=SUM(A1)', experiment=cfg)],
                rows=[dict(name='=SUM(A1)', body_ids=['3'], outputs=[summary])],
                results=[dict(config=dict(experiment=cfg), summary=[summary], steps=[0, 1, 2],
                              series=dict(O=dict(baseline=[0, .1, .02345678901234568], intervention=[0, .08, .02], delta=[0, -.02, -.00345678901234568])),
                              recording_file='must-not-load.npz', states=object())],
                condition_statuses=[dict(name='=SUM(A1)', status='completed'), dict(name='@not-run', status='not_run')],
                constraints=[dict(name='=SUM(A1)', constraints=dict(condition_results=[judgments]))])


class OfflineReportTests(unittest.TestCase):
    def test_saved_values_statuses_security_and_csv_precision(self):
        source = fixture()
        with patch('cecropis.simulation.simulate', side_effect=AssertionError('No propagation')), \
                patch('numpy.load', side_effect=AssertionError('No state archives')):
            rendered = render_report(source)
        report = rendered['report']
        self.assertEqual(report['identity']['actual_index_id'], 'local-uuid')
        self.assertEqual(report['identity']['source_index_id'], 'source-uuid')
        self.assertEqual(report['scope']['internal_edge_count'], 2)
        self.assertEqual(report['conditions'][1]['curves'], {})
        self.assertEqual(report['conditions'][1]['status'], 'not_run')
        page = rendered['files']['report.html']
        self.assertIn('&lt;img', page)
        self.assertNotIn('<img', page)
        self.assertNotIn('<script', page)
        self.assertNotIn('src=', page.replace('&lt;img src=', ''))
        self.assertNotIn('F:\\', page)
        self.assertNotIn('must-not-load', page)
        self.assertIn('Undefined', page)  # Direct API calls default to English.
        self.assertIn('Target · Relative decrease · At least 0.2', page)
        self.assertIn('Satisfied: No', page)
        metric_rows = list(csv.DictReader(io.StringIO(rendered['files']['metrics.csv'])))
        self.assertEqual(metric_rows[0]['condition'], "'=SUM(A1)")
        self.assertEqual(float(metric_rows[0]['baseline_sum']), source['results'][0]['summary'][0]['baseline_sum'])
        self.assertEqual(metric_rows[0]['target_satisfied'], 'False')
        curve_rows = list(csv.DictReader(io.StringIO(rendered['files']['curves.csv'])))
        self.assertEqual(float(curve_rows[2]['baseline']), source['results'][0]['series']['O']['baseline'][2])
        self.assertEqual(curve_rows[-1]['state_step'], '')
        self.assertEqual(curve_rows[-1]['status'], 'not_run')
        self.assertTrue(source['results'][0]['states'])  # Source is not rewritten.
        self.assertEqual(rendered['total_bytes'], sum(len(v.encode('utf-8')) for v in rendered['files'].values()))

    def test_named_protection_with_path_word_is_not_discarded(self):
        source=fixture()
        row=source['constraints'][0]['constraints']['condition_results'][0]
        row['protected_constraints']['path_output']=row['protected_constraints'].pop('O')
        report=extract_report(source)
        self.assertIn('path_output',report['conditions'][0]['constraints'][0]['protected_constraints'])
        self.assertIn('Dataset version: Not recorded',render_report(source)['files']['report.html'])

    def test_all_six_languages_preserve_machine_fields_values_and_user_names(self):
        from cecropis.offline_report import LANGUAGES, ReportText
        from cecropis.api import preview_result_report
        source=fixture()
        baseline=render_report(source)
        for language in LANGUAGES:
            with self.subTest(language=language):
                rendered=render_report(source,language=language)
                text=ReportText(language)
                page=rendered['files']['report.html']
                self.assertIn('lang="'+language+'"',page)
                self.assertIn('<title>Cecropis · ',page)
                for key in ('baseline_mean','noCurves','atLeast','atMost','axis','configuration'):
                    self.assertIn(text(key),page)
                self.assertIn(text.code('status','not_run'),page)
                self.assertIn('=SUM(A1)',page)
                self.assertEqual(rendered['report'],baseline['report'])
                for name in ('metrics.csv','curves.csv'):
                    self.assertEqual(rendered['files'][name],baseline['files'][name])
                preview=preview_result_report(source,language=language,include_html=True)
                self.assertEqual(preview['preview_html'],page)
                self.assertEqual(preview['propagation_count'],0)
        with self.assertRaisesRegex(ValueError,'Unsupported report language'):
            render_report(source,language='unsupported')

    def test_undefined_relative_size_selection_and_new_directory(self):
        source = fixture()
        source['results'][0]['summary'][0]['relative_sum_delta'] = None
        source['results'][0]['summary'][0]['baseline_near_zero'] = True
        rendered = render_report(source, ['=SUM(A1)'])
        row = list(csv.DictReader(io.StringIO(rendered['files']['metrics.csv'])))[0]
        self.assertEqual(row['relative_sum_delta'], '')
        self.assertEqual(rendered['condition_names'], ['=SUM(A1)'])
        with self.assertRaisesRegex(ValueError, 'requires.*bytes'):
            render_report(source, max_bytes=100)
        with self.assertRaisesRegex(ValueError, 'Unknown saved'):
            render_report(source, ['missing'])
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
            dest = Path(folder) / 'new-report'
            saved = export_report(source, dest)
            self.assertEqual((dest / 'report.html').read_text(encoding='utf-8'), render_report(source)['files']['report.html'])
            self.assertEqual(saved['propagation_count'], 0)
            self.assertEqual(saved['sizes'], {name: (dest / name).stat().st_size for name in saved['sizes']})
            with self.assertRaisesRegex(ValueError, 'already exists'):
                export_report(source, dest)
            self.assertEqual(list(Path(folder).glob('.*.tmp')), [])

    def test_old_fixed_source_missing_records_and_safe_read(self):
        source = fixture()
        source.pop('task_definition')
        source.pop('condition_statuses')
        source.pop('actual_data_identity')
        source['results'][0].pop('states')
        source['results'][0].pop('series')
        report = extract_report(source)
        self.assertEqual(report['conditions'][0]['status'], 'completed')
        self.assertEqual(report['conditions'][0]['curves'], {})
        self.assertEqual(report['conditions'][0]['input_events'][0]['body_ids'], ['1'])
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
            (Path(folder) / 'comparison.json').write_text(json.dumps(source), encoding='utf-8')
            with patch('numpy.load', side_effect=AssertionError('No archive load')):
                render_report(folder)
        source['results'][0]['series'] = dict(O=dict(baseline=[0], intervention=[0]))
        with self.assertRaisesRegex(ValueError, 'curve length'):
            render_report(source)


if __name__ == '__main__':
    unittest.main()
