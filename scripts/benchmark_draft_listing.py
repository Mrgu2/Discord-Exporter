#!/usr/bin/env python3
"""Synthetic list/read/JSON benchmark; never opens the real archive or network."""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent
if str(SOURCE) not in sys.path:
    sys.path.insert(0,str(SOURCE))
from discord_archive.editorial import DraftService


def benchmark(count=1000, repeats=5):
    with tempfile.TemporaryDirectory(prefix='archive-draft-list-') as root:
        service = DraftService(None,root,None,None)
        proof = {'sources':['synthetic proof '*8]*400}
        for index in range(count):
            folder = service.output/f'{index:06d}'
            folder.mkdir()
            value = {'id':f'{index:06d}','title':f'合成稿件 {index:06d}',
                'status':'ready','created_at':f'2026-10-{index%28+1:02d}T10:00:00Z',
                'render_verification':proof,'image_variants':{'1':{'images':['image.png'],
                    'render_scale':1,'render_verification':proof}}}
            (folder/'metadata.json').write_text(json.dumps(value,ensure_ascii=False))
        def measure(call):
            samples, size = [],0
            for _ in range(repeats):
                start = time.perf_counter()
                size = len(json.dumps(call(),ensure_ascii=False).encode())
                samples.append((time.perf_counter()-start)*1000)
            return {'median_ms':round(statistics.median(samples),3),'samples_ms':[round(item,3) for item in samples],
                'json_bytes':size}
        baseline = measure(service.list_drafts)
        start = time.perf_counter()
        cold = service.list_draft_page()
        cold_ms = round((time.perf_counter()-start)*1000,3)
        page = measure(service.list_draft_page)
        recent = measure(lambda:service.list_draft_page(limit=3))
        search = measure(lambda:service.list_draft_page(search=f'{count-1:06d}'))
        pages = [service.list_draft_page(offset=offset) for offset in range(0,count,20)]
        ids = [item['id'] for page_value in pages for item in page_value['items']]
        expected = sorted(service.list_drafts(),key=lambda row:(row['created_at'],row['id']),reverse=True)
        assert ids == [item['id'] for item in expected]
        assert len(set(ids)) == count
        assert cold['total'] == count
        assert len(service.list_draft_page(search=f'{count-1:06d}')['items']) == 1
        return {'fictional_only':True,'draft_count':count,'page_size':20,'baseline_full_list_and_json':baseline,
            'cold_light_index_ms':cold_ms,'warm_page_and_json':page,'warm_recent_and_json':recent,
            'warm_full_library_title_search_and_json':search,'all_pages_equal':True,
            'cache_projection_json_bytes':len(json.dumps([row[1] for row in service._draft_listing_cache.values()],ensure_ascii=False).encode()),
            'scope':'Warm filesystem reads and Python JSON; excludes HTTP, browser layout and disk-cold startup.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--drafts',type=int,default=1000)
    parser.add_argument('--repeats',type=int,default=5)
    args = parser.parse_args()
    if not 1 <= args.drafts <= 10000 or not 1 <= args.repeats <= 20:
        parser.error('drafts must be 1..10000 and repeats 1..20')
    print(json.dumps(benchmark(args.drafts,args.repeats),ensure_ascii=False,indent=2))
