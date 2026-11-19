"""Wrapping review tables with natural row heights and complete cell text."""
import html
import re
import math
import pandas as pd
import streamlit as st

def table_html(data):
    frame=data if isinstance(data,pd.DataFrame) else pd.DataFrame(data)
    if frame.empty:return '<p>No records to display.</p>'
    def cell(value):
        if value is None:return '—'
        if isinstance(value,float):
            if not math.isfinite(value):return '—'
            if value.is_integer():value=int(value)
        escaped=html.escape(str(value).replace('Precision and accuracy / calibration and QC','Precision and Accuracy')).replace('\n','<br>')
        return re.sub(r'\[([^\]]+)\]\((https?://[^\s<>]+)\)',r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>',escaped)
    headers=''.join('<th scope="col">'+cell(c)+'</th>' for c in frame.columns)
    rows=''.join('<tr>'+''.join('<td>'+cell(v)+'</td>' for v in values)+'</tr>' for values in frame.itertuples(index=False,name=None))
    minimum=max(0,len(frame.columns)*145)
    return '''<style>
    .bio-table-scroll{width:100%;overflow-x:auto;margin:0.5rem 0 1rem}
    .bio-review-table{width:100%;border-collapse:collapse;table-layout:fixed;color:inherit;font:inherit}
    .bio-review-table th,.bio-review-table td{white-space:normal!important;overflow-wrap:anywhere;word-break:normal;
      vertical-align:top;text-align:left;padding:0.65rem 0.75rem;border:1px solid rgba(128,128,128,.3);
      height:auto;max-height:none;line-height:1.5;overflow:visible;text-overflow:clip}
    .bio-review-table th{background:rgba(128,128,128,.10);font-weight:600}
    </style><div class="bio-table-scroll" role="region" aria-label="Full text review table" tabindex="0"><table class="bio-review-table" style="min-width:MINIMUMpx"><thead><tr>HEADERS</tr></thead><tbody>ROWS</tbody></table></div>'''.replace('MINIMUM',str(minimum)).replace('HEADERS',headers).replace('ROWS',rows)

def readable_table(data,**_presentation_options):
    st.markdown(table_html(data),unsafe_allow_html=True)
