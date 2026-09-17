from pathlib import Path

path = Path('index.html')
html = path.read_text(encoding='utf-8')
needle = '\n\nasync function loadChecklistData(){'
if 'function clRefresh(){' in html:
    print('clRefresh already present')
    raise SystemExit(0)
if needle not in html:
    raise SystemExit('loadChecklistData anchor not found')
refresh = "\nfunction clRefresh(){\n  clApplyFilters();\n  clRenderKPIs();\n  clRenderHeatmap();\n  clRenderRankChart();\n  clRenderTrend();\n  clRenderTable();\n}\n"
html = html.replace(needle, refresh + needle, 1)
path.write_text(html, encoding='utf-8')
print('Restored clRefresh')
