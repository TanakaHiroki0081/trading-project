//+------------------------------------------------------------------+
//|                                                SlaveEA_HTTP.mq5 |
//|   Polls backend for trade signals (JSON) and executes them       |
//+------------------------------------------------------------------+
#property strict

input string BACKEND_URL = "http://127.0.0.1:8000/poll";  // REST polling endpoint

//--- Initialization
int OnInit()
{
   EventSetTimer(2); // poll every 2 seconds
   Print("✅ Slave EA started (HTTP polling). Make sure URL is allowed in MT5 Options.");
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   Print("❌ Slave EA stopped");
}

//--- Timer: poll backend
void OnTimer()
{
   uchar data[];        // empty body for GET request
   uchar result[];      // response will be stored here
   string headers;      // response headers will be stored here

   int status = WebRequest("GET", BACKEND_URL, "", 5000, data, result, headers);

   if(status == -1)
   {
      Print("⚠️ WebRequest failed. Did you allow URL in MT5? ", BACKEND_URL,
            " (Tools → Options → Expert Advisors → Allow WebRequest)");
      return;
   }

   string response = "";
   if(ArraySize(result) > 0)
      response = CharArrayToString(result);

   if(StringLen(response) > 2) // avoid empty {}
   {
      Print("📥 Received trade JSON: ", response);
      ExecuteTrade(response);
   }
}

//--- Simple JSON helper: extract value by key
string GetJsonValue(string json, string key)
{
   string pattern = "\"" + key + "\":";
   int start = StringFind(json, pattern);
   if(start == -1) return("");

   start += StringLen(pattern);

   // check if value is string (inside quotes)
   if(StringGetCharacter(json, start) == '\"')
   {
      start++;
      int end = StringFind(json, "\"", start);
      if(end == -1) return("");
      return StringSubstr(json, start, end - start);
   }
   else
   {
      int end = StringFind(json, ",", start);
      if(end == -1) end = StringFind(json, "}", start);
      if(end == -1) return("");
      string value = StringSubstr(json, start, end - start);
      StringTrimLeft(value);
      StringTrimRight(value);
      return value;
   }
}

//--- Execute received trade
void ExecuteTrade(string json)
{
   // Example JSON:
   // {"symbol":"XAUUSD","volume":0.1,"type":0,"sl":1900.0,"tp":1950.0,"action":"OPEN"}

   string symbol = GetJsonValue(json, "symbol");
   double volume = StringToDouble(GetJsonValue(json, "volume"));
   int type      = (int)StringToInteger(GetJsonValue(json, "type"));
   double sl     = StringToDouble(GetJsonValue(json, "sl"));
   double tp     = StringToDouble(GetJsonValue(json, "tp"));
   string action = GetJsonValue(json, "action");

   if(symbol == "" || volume <= 0 || action != "OPEN")
   {
      Print("⚠️ Invalid or unsupported trade signal: ", json);
      return;
   }

   if(!SymbolSelect(symbol,true))
   {
      Print("⚠️ Symbol not available: ", symbol);
      return;
   }

   MqlTradeRequest req;
   MqlTradeResult res;
   ZeroMemory(req);
   ZeroMemory(res);

   req.action   = TRADE_ACTION_DEAL;
   req.symbol   = symbol;
   req.volume   = volume;
   req.type     = (type==0 ? ORDER_TYPE_BUY : ORDER_TYPE_SELL);
   req.price    = (type==0 ? SymbolInfoDouble(symbol,SYMBOL_ASK)
                           : SymbolInfoDouble(symbol,SYMBOL_BID));
   req.sl       = sl;
   req.tp       = tp;
   req.deviation= 10;
   req.magic    = 123456;
   req.type_filling = ORDER_FILLING_RETURN; // safer filling mode

   if(!OrderSend(req,res))
      Print("❌ OrderSend failed. Error: ", _LastError);
   else
      Print("✅ Executed trade from master. Order ID: ", res.order);
}
