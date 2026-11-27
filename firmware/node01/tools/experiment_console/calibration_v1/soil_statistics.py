"""无滤波描述统计；按attempted归窗，acquired只用于读取完成时序。"""
from collections import Counter
import statistics as st


def quantile(values, p):
    if not values:
        return None
    a = sorted(values)
    x = (len(a) - 1) * p
    i = int(x)
    return a[i] + (a[min(i + 1, len(a) - 1)] - a[i]) * (x - i)


def describe(values):
    return {'min': min(values) if values else None, 'median': st.median(values) if values else None,
            'max': max(values) if values else None}


def channel_statistics(rows, end, channel, subwindow_seconds=10):
    all_rows = [r for r in rows if r['kind'] == 'soil' and r['channel'] == channel]
    start, stop = end['start_us'], end['stop_us']
    group = [r for r in all_rows if start <= r['attempted'] < stop]
    valid = [r for r in group if r['validity'] == 'Valid' and r['raw'] is not None and r['acquired'] is not None]
    values = [r['raw'] for r in valid]
    times = [r['acquired'] for r in valid]
    gaps = [(b-a)/1000000 for a,b in zip(times, times[1:])]
    delays = [(r['acquired']-r['attempted'])/1000000 for r in valid]
    adjacent = [abs(b['raw']-a['raw']) for a,b in zip(group,group[1:])
                if a['validity'] == b['validity'] == 'Valid' and a['raw'] is not None and b['raw'] is not None]
    duration = (stop-start)/1000000
    span = min(subwindow_seconds, duration/2) * 1000000
    first = [r['raw'] for r in valid if r['attempted'] < start+span]
    last = [r['raw'] for r in valid if r['attempted'] >= stop-span]
    drift = st.mean(last)-st.mean(first) if first and last else None
    slope = None
    if len(times)>1:
        x = [(t-start)/1000000 for t in times]
        xbar, ybar = st.mean(x), st.mean(values)
        denom = sum((t-xbar)**2 for t in x)
        slope = sum((t-xbar)*(y-ybar) for t,y in zip(x,values))/denom if denom else None
    return {'channel':channel,'role':'DIAGNOSTIC_ONLY' if channel==2 else 'REFERENCE_REVIEW',
        'N_attempted':len(group),'N_valid':len(valid),'N_unavailable':sum(r['validity']=='Unavailable' for r in group),
        'N_error':sum(r['validity']=='Error' for r in group),'error_codes':dict(Counter(str(r['error']) for r in group)),
        'mean':st.mean(values) if values else None,'median':st.median(values) if values else None,
        'sample_sd':st.stdev(values) if len(values)>1 else None, 'min':min(values) if values else None,
        'max':max(values) if values else None,'p5':quantile(values,.05),'p95':quantile(values,.95),
        'adjacent_abs_median':st.median(adjacent) if adjacent else None,'adjacent_abs_max':max(adjacent) if adjacent else None,
        'jumps_gt20':sum(v>20 for v in adjacent),'jumps_gt50':sum(v>50 for v in adjacent),'jumps_gt100':sum(v>100 for v in adjacent),
        'subwindow_seconds':span/1000000,'first_last_mean_difference':drift,'ols_raw_per_second':slope,
        'valid_rate_window_hz':len(valid)/duration,'valid_rate_endpoint_hz':(len(times)-1)*1000000/(times[-1]-times[0]) if len(times)>1 and times[-1]>times[0] else None,
        'target_rate_hz':2.0,'rate_difference_hz':len(valid)/duration-2.0,'gap_seconds':describe(gaps),
        'gap_exceeds_target_count':sum(g>.5 for g in gaps), 'latency_seconds':describe(delays),
        'latency_exceeds_40ms_count':sum(d>.04 for d in delays),
        'attempted_monotonic':all(a['attempted']<b['attempted'] for a,b in zip(all_rows,all_rows[1:])),
        'acquired_monotonic':all(a<b for a,b in zip(times,times[1:])),
        'boundary_inflight_count':sum(r['acquired']>=stop for r in valid),
        'out_of_window_attempts':len(all_rows)-len(group), 'quality':'REVIEW_REQUIRED',
        'quality_reasons':['QUALITY_THRESHOLDS_PENDING_USER_APPROVAL']}
