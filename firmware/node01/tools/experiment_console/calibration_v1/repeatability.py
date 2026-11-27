import statistics as st


def summarize(stats, channel, condition):
    selected = [s for s in stats if s['channel']==channel and s['run_role'] in [f'{condition}-{i}' for i in (1,2,3)]]
    means = [s['mean'] for s in selected if s['mean'] is not None]
    return {'channel':channel,'condition':condition,'run_count':len(selected),
            'roles':[s['run_role'] for s in selected],'experiment_ids':[s['experiment_id'] for s in selected],
            'run_means':means,'mean_range':max(means)-min(means) if means else None,
            'run_mean_sample_sd':st.stdev(means) if len(means)>1 else None,
            'within_run_sample_sd':[s['sample_sd'] for s in selected],
            'within_run_drift':[s['first_last_mean_difference'] for s in selected],
            'endpoint_equal_run_weight':st.mean(means) if len(means)==3 and len(selected)==3 else None}
