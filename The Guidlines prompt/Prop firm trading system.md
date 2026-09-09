Prop Firm trading system guidlines

The system should be:

Optimized for:
	-Profit factor, draw down control, consistancy, low corrolation between trades and Low probability of a catastrophic day

Use Draw down control:
	-Hard stop at 1.5% daily Draw Down based onrealized and unrealized PnL close and disable all till daily reset.
	-Hard stop at 5% Max draw down based on realized and unrealized PnL on intitial balance close all and disable trading till manual reset.
	-Hard stop at 3 consecutive losses Close all and disable trading till manual reset.
	
for firms with no single day profit limits:
	-Hard stop at 35% profit close all and disable trading till daily reset
	
Max lot sizing - Use higher lot sizing (0.50% - 0.75%) for evaluation and lower for funded (0.25% - 0.50%)

Risk to Reward ratio:
	-minimum 1:2
	-Prefered 1:3

Use instruments with:
	-Reliable external data 
	-Deep liquidity
	-Clear cross-market relationship
Recomended assets:

	-Major FX
		-EURUSD
		-GBPUSD
		=USDJPY
		-AUDUSD
		-USDCAD
		
	-Major indices
		-NAS100
		-US500
		-GER40
		-UK100
	-Metals
		-Gold
		
Advantages:

high liquidity;
deep futures markets;
macro relationships;
relatively clean data
	
Trade decision:
	-Signal strength
	-order flow confirmation
	-Trend regime
	-Volotility regime
	-Risk availability

Inputs can include:

Gold futures
USD
Treasury yields
Equity volatility

Futures lead indicator:
	-Monitor
		-Assets futures
		-Asset spot
		-Dollar index
		-European equity futures
		-US Treasury yields
use to calculate short term changes

Trade signal formula:
	-Signal=w1​(FuturesMomentum)+w2​(OrderFlow)+w3​(LeadLag)+w4​(MacroConfirmation)−w5​(VolatilityRisk)
	
Signal generation examples:
	-Futures:      strongly bullish
	-Spot:         weak
	-DXY:          bearish
	-Volatility:   normal
	
	-Signal
		-LONG (Asset ie USDCAD)
		-Confidence: 82%

Regime detection:
	-TRENDING
	-MEAN REVERTING
	-HIGH VOLATILITY
	-LOW LIQUIDITY
	-NEWS RISK
Regime detectin examples:
	-TRENDING  Momentum strategy ON
	-MEAN REVERTING  Reversion strategy ON
	-NEWS RISK All No new positions 30 minuts before and after OFF
	
Trade execution approval:
	-Is daily loss acceptable?          YES
	-Is total drawdown acceptable?      YES
	-Is correlation acceptable?         YES
	-Is spread acceptable?              YES
	=Is volatility acceptable?          YES
	-Is slipage applicable?    			YES
	-Is news restriction in effect		NO
	
Result Execute trade

Exit Strategy:
	-+0.5% no changes
	-+1.0% Breakeven Logic (+0.05%+Commision)
	-+2% Trailing logic (tight trailing stop)
	
Stratagies:
	-Cross-Market confirmation
	-Future's to CFD's lead lag (setup as prodictive trading not latancey)
	-Regime based momentum
	-Statistical mean reversion
	
Real time Data sources:
	-News Forex factory
	-Forex MT5

Final notes:
	-futures markets as information inputs
	-use futures and higher time frame for direction
	-multi-market confirmation
	-execute only when the signal survives transaction costs and prop-firm risk constraints
	-place an independent risk engine above the strategy
	-Signal the user on platform alerts audio and visual. external alerts Email, telegram, cellphone and push notification
		
System Build:
	-modular
	=fast execution
	-detailed logging for debugging
	-Automatic trade jounaling
	-Manual override MT5 Dashboard that closes all trades and stops trading till manual reset
	
Coding languages to use:
	-Python to bridge to MT5
	-Go for backend procces's
	-Rust for signal generation
	-MT5 for trade execution
	
Using the above guidlines I need the following built:
	- An MT5 dashboard for manual override (Human in the loop)
	- A completly automated system version
	
Possible Additions:
	-Trade confirmation via Forex Factory live trades and/or trader sentiment