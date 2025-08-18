//+------------------------------------------------------------------+
//|                                                      SlaveEA_WSbridge.mq5 |
//|  Slave EA that gets near-real-time events via a local bridge HTTP endpoint |
//+------------------------------------------------------------------+
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>

//--- Settings
input string BRIDGE_URL = "http://127.0.0.1:9000/events"; // local bridge
input double LOT_MULTIPLIER = 1.0;  // multiply master lots
input int POLL_INTERVAL = 1;        // seconds between polls (bridge is long-polling)
input int WEBREQUEST_TIMEOUT = 35000; // ms
input int SLAVE_MAGIC = 9999;       // magic for slave orders

//--- State
ulong processedTickets[];  // tickets already processed

//--- Helpers
void StringToUtf8(string s, uchar &out[])
{
   int len = StringToCharArray(s, out, 0, WHOLE_ARRAY, CP_UTF8);
   if(len>0) ArrayResize(out, len-1); // remove null term
}

string CharArrayToUtf8String(uchar &arr[])
{
   return(CharArrayToString(arr, 0, WHOLE_ARRAY, CP_UTF8));
}

bool IsProcessed(ulong ticket)
{
   for(int i=0;i<ArraySize(processedTickets);i++)
      if(processedTickets[i]==ticket) return true;
   return false;
}

void MarkProcessed(ulong ticket)
{
   if(!IsProcessed(ticket))
   {
      ArrayResize(processedTickets, ArraySize(processedTickets)+1);
      processedTickets[ArraySize(processedTickets)-1] = ticket;
   }
}

//--- Minimal JSON parsing helpers (robust lib recommended for production)
string json_get_string_field(const string json,const string key)
{
   string pattern = "\"" + key + "\":";
   int pos = StringFind(json, pattern);
   if(pos==-1) return("");
   pos += StringLen(pattern);
   // skip whitespace and optional quote
   while(pos < StringLen(json) && (StringGetCharacter(json,pos)==32 || StringGetCharacter(json,pos)==9)) pos++;
   if(StringGetCharacter(json,pos)=='"')
   {
      pos++; int start=pos;
      while(pos < StringLen(json) && StringGetCharacter(json,pos)!='"') pos++;
      return StringSubstr(json, start, pos-start);
   }
   // not a quoted string; read until comma or brace
   int end = StringFind(json, ",", pos);
   if(end==-1) end = StringFind(json, "}", pos);
   if(end==-1) end = StringLen(json);
   return StringSubstr(json, pos, end-pos);
}

double json_get_number_field(const string json,const string key)
{
   string s = json_get_string_field(json,key);
   if(s=="") return 0.0;
   return StringToDouble(s);
}

long json_get_int_field(const string json,const string key)
{
   string s = json_get_string_field(json,key);
   if(s=="") return 0;
   return (long)StringToInteger(s);
}

//--- Trade actions
void HandleEvent(const string raw_event)
{
   // raw_event is a JSON object string
   // Extract fields
   ulong ticket = (ulong)json_get_int_field(raw_event,"ticket");
   string symbol = json_get_string_field(raw_event,"symbol");
   double volume = json_get_number_field(raw_event,"volume");
   double sl = json_get_number_field(raw_event,"sl");
   double tp = json_get_number_field(raw_event,"tp");
   int type = (int)json_get_int_field(raw_event,"type"); // 0=buy,1=sell
   string action = json_get_string_field(raw_event,"action");

   if(IsProcessed(ticket) && action=="OPEN")
      return;

   double adjVol = volume * LOT_MULTIPLIER;
   MqlTradeRequest req;
   MqlTradeResult res;
   ZeroMemory(req);
   ZeroMemory(res);

   if(action=="OPEN")
   {
      req.action = TRADE_ACTION_DEAL;
      req.symbol = symbol;
      req.volume = NormalizeDouble(adjVol,2); // adjust precision if needed
      req.type = (type==0) ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
      req.price = (req.type==ORDER_TYPE_BUY) ? SymbolInfoDouble(symbol,SYMBOL_ASK) : SymbolInfoDouble(symbol,SYMBOL_BID);
      req.sl = sl;
      req.tp = tp;
      req.magic = SLAVE_MAGIC;
      req.deviation = 10;
      req.comment = "Slave copy";
      if(!OrderSend(req,res))
         PrintFormat("Failed OrderSend OPEN: err=%d res=%d", GetLastError(), res.retcode);
      else
      {
         PrintFormat("Opened symbol=%s ticket=%I64u master_ticket=%I64u ret=%d", symbol, (ulong)res.order, ticket, res.retcode);
         MarkProcessed(ticket);
      }
   }
   else if(action=="CLOSE")
   {
      // Try to close positions matching master ticket by comment/magic/symbol
      CPositionInfo m_position;
      for(int i=PositionsTotal()-1; i>=0; i--)
      {
         if(m_position.SelectByIndex(i))
         {
            string psym = m_position.Symbol();
            long pmagic = m_position.Magic();
            ulong p_ticket = m_position.Ticket();
            if(psym==symbol && pmagic==SLAVE_MAGIC)
            {
               ZeroMemory(req); ZeroMemory(res);
               req.action = TRADE_ACTION_DEAL;
               req.position = p_ticket;
               long ptype = m_position.PositionType();
               req.type = (ptype==POSITION_TYPE_BUY) ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;
               req.volume = m_position.Volume();
               req.symbol = symbol;
               req.price = (req.type==ORDER_TYPE_BUY) ? SymbolInfoDouble(symbol,SYMBOL_ASK) : SymbolInfoDouble(symbol,SYMBOL_BID);
               req.deviation = 10;
               req.comment = "Slave close";
               req.magic = SLAVE_MAGIC;
               if(!OrderSend(req,res))
                  PrintFormat("Failed OrderSend CLOSE: err=%d ret=%d", GetLastError(), res.retcode);
               else
                  PrintFormat("Closed slave pos %I64u for symbol=%s ret=%d", p_ticket, symbol, res.retcode);
            }
         }
      }
      MarkProcessed(ticket);
   }
   else if(action=="MODIFY")
   {
      CPositionInfo m_position;
      for(int i=PositionsTotal()-1;i>=0;i--)
      {
         if(m_position.SelectByIndex(i))
         {
            string psym = m_position.Symbol();
            long pmagic = m_position.Magic();
            ulong p_ticket = m_position.Ticket();
            if(psym==symbol && pmagic==SLAVE_MAGIC)
            {
               double curSL = m_position.StopLoss();
               double curTP = m_position.TakeProfit();
               if(curSL!=sl || curTP!=tp)
               {
                  ZeroMemory(req); ZeroMemory(res);
                  req.action = TRADE_ACTION_SLTP;
                  req.position = p_ticket;
                  req.sl = sl;
                  req.tp = tp;
                  if(!OrderSend(req,res))
                     PrintFormat("Failed modify pos %I64u err=%d ret=%d", p_ticket, GetLastError(), res.retcode);
                  else
                     PrintFormat("Modified pos %I64u ret=%d", p_ticket, res.retcode);
               }
            }
         }
      }
      MarkProcessed(ticket);
   }
}

//--- Poll bridge (long-poll)
void PollBridge()
{
   uchar post[], result[];
   string headers = "Content-Type: application/json";
   string result_headers;
   ResetLastError();

   int res = WebRequest("GET", BRIDGE_URL, headers, WEBREQUEST_TIMEOUT, post, result, result_headers);
   if(res == -1)
   {
      PrintFormat("WebRequest failed: %d. Check Allowed URLs in MT5 options for: %s", GetLastError(), BRIDGE_URL);
      return;
   }

   string response = CharArrayToUtf8String(result);
   if(StringLen(response) == 0) return;

   // Look for '"events":[' and extract the array
   int pos = StringFind(response, "\"events\":[");
   if(pos == -1) return;
   pos += StringLen("\"events\":[");
   int end = StringFind(response, "]", pos);
   if(end == -1) return;
   string events_str = StringSubstr(response, pos, end-pos);

   // Split by '},{' to get each object
   string items[];
   int cnt = StringSplit(events_str, "},{", items);
   for(int i=0;i<cnt;i++)
   {
      string item = items[i];
      if(i != cnt-1) item = item + "}"; // add closing brace except for last
      if(i != 0) item = "{" + item;     // add opening brace except for first
      HandleEvent(item);
   }
}

//--- Timer
int OnInit()
{
   Print("SlaveEA_WSbridge started");
   EventSetTimer(POLL_INTERVAL);
   return(INIT_SUCCEEDED);
}

void OnTimer()
{
   PollBridge();
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   Print("SlaveEA_WSbridge stopped");
}
