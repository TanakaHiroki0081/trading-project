//+------------------------------------------------------------------+
//|                                                      SlaveEA.mq5 |
//|        Connects to backend and executes trades from Master       |
//+------------------------------------------------------------------+
#property strict

#include <stdlib.mqh>

//--- Settings
input string BACKEND_URL = "http://127.0.0.1:8000/recent"; // You may create this endpoint to return recent events
input double LOT_MULTIPLIER = 1.0;  // Adjust master lot size if needed
input int POLL_INTERVAL = 2;         // seconds

//--- Keep track of executed trades to avoid duplicates
ulong executedTickets[];

//--- Convert UTF-8 char array to string
string CharArrayToStr(uchar &data[])
{
   return(CharArrayToString(data, 0, WHOLE_ARRAY, CP_UTF8));
}

//--- Utility: check if ticket already executed
bool IsExecuted(ulong ticket)
{
   for(int i=0; i<ArraySize(executedTickets); i++)
      if(executedTickets[i] == ticket) return true;
   return false;
}

//--- Execute trade
void ExecuteTrade(string action, string symbol, double volume, double sl, double tp, int type, ulong ticket)
{
   double adjVolume = volume * LOT_MULTIPLIER;
   if(action == "OPEN")
   {
      int orderType = type; // 0=BUY,1=SELL in your master EA
      MqlTradeRequest request;
      MqlTradeResult result;
      ZeroMemory(request);
      ZeroMemory(result);

      request.action   = TRADE_ACTION_DEAL;
      request.symbol   = symbol;
      request.volume   = adjVolume;
      request.type     = orderType;
      request.price    = (orderType==ORDER_TYPE_BUY) ? SymbolInfoDouble(symbol,SYMBOL_ASK) : SymbolInfoDouble(symbol,SYMBOL_BID);
      request.sl       = sl;
      request.tp       = tp;
      request.magic    = 9999; // Set slave magic number
      request.comment  = "Slave copy";

      if(!OrderSend(request,result))
         Print("❌ Failed to open ", symbol, " ticket=", ticket, " err=",GetLastError());
      else
         Print("✅ Opened ", symbol, " ticket=", ticket, " result:", result.retcode);
   }
   else if(action == "CLOSE")
   {
      // Find position by ticket
      if(PositionSelectByTicket(ticket))
      {
         double closeVolume = PositionGetDouble(POSITION_VOLUME);
         MqlTradeRequest request;
         MqlTradeResult result;
         ZeroMemory(request);
         ZeroMemory(result);

         request.action   = TRADE_ACTION_DEAL;
         request.position = ticket;
         request.symbol   = symbol;
         request.volume   = closeVolume;
         request.type     = (PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY) ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;
         request.price    = (request.type==ORDER_TYPE_BUY) ? SymbolInfoDouble(symbol,SYMBOL_ASK) : SymbolInfoDouble(symbol,SYMBOL_BID);
         request.magic    = 9999;
         request.comment  = "Slave copy";

         if(!OrderSend(request,result))
            Print("❌ Failed to close ", symbol, " ticket=", ticket, " err=",GetLastError());
         else
            Print("✅ Closed ", symbol, " ticket=", ticket, " result:", result.retcode);
      }
   }
   else if(action == "MODIFY")
   {
      if(PositionSelectByTicket(ticket))
      {
         double currentSL = PositionGetDouble(POSITION_SL);
         double currentTP = PositionGetDouble(POSITION_TP);

         if(currentSL != sl || currentTP != tp)
         {
            MqlTradeRequest request;
            MqlTradeResult result;
            ZeroMemory(request);
            ZeroMemory(result);

            request.action   = TRADE_ACTION_SLTP;
            request.position = ticket;
            request.sl       = sl;
            request.tp       = tp;

            if(!OrderSend(request,result))
               Print("❌ Failed to modify ", symbol, " ticket=", ticket, " err=",GetLastError());
            else
               Print("✅ Modified ", symbol, " ticket=", ticket, " result:", result.retcode);
         }
      }
   }
   // Record executed ticket to avoid re-processing
   if(!IsExecuted(ticket))
   {
      ArrayResize(executedTickets,ArraySize(executedTickets)+1);
      executedTickets[ArraySize(executedTickets)-1] = ticket;
   }
}

//--- Poll backend for recent trades
void PollBackend()
{
   uchar post[], result[];
   string result_headers;

   ResetLastError();
   int res = WebRequest("GET", BACKEND_URL, "", 5000, post, result, result_headers);
   if(res == -1)
   {
      PrintFormat("❌ WebRequest failed: %d", GetLastError());
      return;
   }

   string response = CharArrayToStr(result);
   // Expected: response is JSON list of trade events
   // Example: [{"ticket":123,"symbol":"EURUSD","volume":0.1,"sl":1.1,"tp":1.2,"type":0,"magic":1,"comment":"x","action":"OPEN"}, ...]
   if(StringLen(response) > 0)
   {
      int arrSize = 0;
      // Parse simple JSON manually (you may use JSON.mqh library for robustness)
      // For simplicity here, use StringSplit by '{' and '}'
      string items[];
      arrSize = StringSplit(response, '{', items);
      for(int i=1;i<arrSize;i++) // skip first empty
      {
         string s = "{" + items[i];
         // Extract fields
         ulong ticket = StringToInteger(StringGetField(s,"ticket"));
         string symbol = StringGetField(s,"symbol");
         double volume = StringToDouble(StringGetField(s,"volume"));
         double sl     = StringToDouble(StringGetField(s,"sl"));
         double tp     = StringToDouble(StringGetField(s,"tp"));
         int type      = StringToInteger(StringGetField(s,"type"));
         string action = StringGetField(s,"action");

         if(!IsExecuted(ticket))
            ExecuteTrade(action,symbol,volume,sl,tp,type,ticket);
      }
   }
}

//--- Initialization
int OnInit()
{
   Print("Slave EA started");
   EventSetTimer(POLL_INTERVAL);
   return(INIT_SUCCEEDED);
}

//--- Timer tick
void OnTimer()
{
   PollBackend();
}

//--- Deinitialization
void OnDeinit(const int reason)
{
   EventKillTimer();
   Print("Slave EA stopped");
}

//--- Simple helper to extract JSON field (very basic)
string StringGetField(string json, string key)
{
   int pos = StringFind(json, "\"" + key + "\":");
   if(pos == -1) return "";
   int start = pos + StringLen(key) + 3; // skip key+quotes+colon
   int end = StringFind(json, ",", start);
   if(end == -1) end = StringFind(json, "}", start);
   return StringSubstr(json,start,end-start);
}
