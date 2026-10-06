import runpy
import requests

BASE = "https://pro-api.coinmarketcap.com/public-api/v3/cryptocurrency/quotes/latest"
SLUGS = {
    "BTC":"bitcoin","XLM":"stellar","ARB":"arbitrum","ENA":"ethena","SUI":"sui","ICP":"internet-computer","QNT":"quant","UNI":"uniswap","XRP":"xrp","AXL":"axelar","LINK":"chainlink","ALGO":"algorand","ADA":"cardano","SOL":"solana","OP":"optimism","ONDO":"ondo-finance","IOTA":"iota","BABY":"babylon","APT":"aptos","AIOZ":"aioz-network","LMWR":"limewire","EIGEN":"eigenlayer","FET":"artificial-superintelligence-alliance","ETH":"ethereum","W":"wormhole",
    "TRX":"tron","HYPE":"hyperliquid","ZEC":"zcash","DOGE":"dogecoin","XMR":"monero","LTC":"litecoin","AVAX":"avalanche","TAO":"bittensor","SHIB":"shiba-inu","AAVE":"aave","WLD":"worldcoin-org","WLFI":"world-liberty-financial-wlfi","KAS":"kaspa","POL":"polygon-ecosystem-token","RENDER":"render-token","FIL":"filecoin","CAKE":"pancakeswap","NIGHT":"midnight","ZRO":"layerzero","INJ":"injective","STX":"stacks","CRV":"curve-dao-token","PENDLE":"pendle","GRT":"the-graph","AR":"arweave","RUNE":"thorchain","COMP":"compound","WIF":"dogwifhat","THETA":"theta","MINA":"mina","SUPER":"superverse","ATH":"aethir","1INCH":"1inch","ZRX":"0x","DOG":"dog-go-to-the-moon-rune","GMX":"gmx","SUSHI":"sushi","CKB":"nervos-network","REQ":"request","ALEO":"aleo","COTI":"coti","MANTRA":"mantra-dao","SKL":"skale","TAIKO":"taiko","STORJ":"storj"
}

_original_get = requests.get

def fixed_get(url, *args, **kwargs):
    params = kwargs.get("params")
    if url == BASE and isinstance(params, dict) and params.get("symbol"):
        symbols = [s.strip().upper() for s in str(params["symbol"]).split(",")]
        fixed_params = dict(params)
        fixed_params["slug"] = ",".join(SLUGS.get(s, s.lower()) for s in symbols)
        fixed_params.pop("symbol", None)
        kwargs["params"] = fixed_params
    return _original_get(url, *args, **kwargs)

requests.get = fixed_get
runpy.run_path("crypto_monitor.py", run_name="__main__")
