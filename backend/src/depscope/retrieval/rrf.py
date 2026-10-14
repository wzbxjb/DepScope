from collections import defaultdict


def rrf(rankings,k=60):
    if k<=0:raise ValueError("RRF constant must be positive")
    scores=defaultdict(float)
    for ranking in rankings:
        for position,item in enumerate(dict.fromkeys(ranking),start=1):scores[item]+=1/(k+position)
    return tuple(sorted(scores,key=lambda item:(-scores[item],item)))
