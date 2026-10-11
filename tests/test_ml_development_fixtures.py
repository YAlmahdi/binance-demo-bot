"""Synthetic model fixtures: never historical fitting or performance evidence."""
from dataclasses import replace
from decimal import Decimal
import math
from demo_futures.ml_research.config import START,STEP,BUFFER
from demo_futures.ml_research.features import FeatureRow
from demo_futures.ml_research.labels import LabelResult,label_opportunity
from demo_futures.ml_research.development_data import TrainingPartition
from demo_futures.backtest import FundingEvent
from test_ml_fixtures import candle,opportunity


def synthetic_partition(count=240,day_blocks=False):
    bars=[candle(i) for i in range(49)]
    base=label_opportunity(opportunity(bars),bars,(FundingEvent(START,".001",100),)).trade
    features=[];labels=[]
    for i in range(count):
        t=START+(i//12*86_400_000+i%12*STEP if day_blocks else i*STEP)+STEP-1
        symbol="ETHUSDT" if i%3==0 else "BTCUSDT";side="LONG" if i%4<2 else "SHORT";y=i%2
        values=tuple((y*2-1)*(1+j/20)+math.sin(i+j)*.3 for j in range(14))+(float(symbol=="ETHUSDT"),float(side=="LONG"))
        rid=f"{symbol}:{t}";net=Decimal(2 if y else -3)
        trade=replace(base,symbol=symbol,side=side,signal_time=t,entry_time=t+1,exit_time=t+STEP,
                      net_pnl=net,gross_pnl=net+base.slippage_cost+base.fees+base.funding_cost)
        features.append(FeatureRow(rid,symbol,t,t,values))
        labels.append(LabelResult(rid,symbol,t,t+1,t+1+BUFFER,"VALID","Synthetic only",y,trade))
    return TrainingPartition(1,tuple(features),tuple(labels))
