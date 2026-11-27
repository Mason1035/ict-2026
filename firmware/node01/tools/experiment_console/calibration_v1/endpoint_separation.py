"""端点分离描述与非裁剪相对指数；禁止使用AIN2构造参数。"""
from .common import require


def separation(stats, channel, air, water):
    a=[s for s in stats if s['channel']==channel and s['run_role'].startswith('AIR-')]
    w=[s for s in stats if s['channel']==channel and s['run_role'].startswith('WATER-')]
    pairs=[(x['mean'],y['mean']) for x in a for y in w if x['mean'] is not None and y['mean'] is not None]
    intervals=[(x['experiment_id'],y['experiment_id'],max(x['p5'],y['p5'])<=min(x['p95'],y['p95']))
               for x in a for y in w if None not in (x['p5'],x['p95'],y['p5'],y['p95'])]
    av,wv=air['endpoint_equal_run_weight'],water['endpoint_equal_run_weight']
    return {'channel':channel,'air_candidate_mean':av,'water_candidate_mean':wv,
            'absolute_endpoint_difference':abs(av-wv) if av is not None and wv is not None else None,
            'direction':('AIR_GT_WATER' if av>wv else 'AIR_LT_WATER' if av<wv else 'EQUAL') if av is not None and wv is not None else 'NOT_AVAILABLE',
            'all_pair_mean_direction_consistent':bool(pairs) and (all(x>y for x,y in pairs) or all(x<y for x,y in pairs)),
            'p5_p95_pair_overlap':any(v for _,_,v in intervals),'interval_pairs':intervals,
            'reference_status':'REFERENCE_NOT_READY'}


def moisture(raw, air, water):
    require(air!=water, '参考端点相等，禁止除零')
    return (air-raw)/(air-water) if air>water else (raw-air)/(water-air)
