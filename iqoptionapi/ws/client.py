#=============================================================================#
#                             API BY: Lucas Code                              #    
#                     https://www.youtube.com/@lucascode                      #
#=============================================================================#
import json
import logging
import websocket
import iqoptionapi.global_value as global_value
import iqoptionapi.constants as OP_code

class WebsocketClient(object):
    def __init__(self, api):
        self.api = api
        if "iqop" not in self.api.wss_url:
            return None 
        else:
            self.wss = websocket.WebSocketApp(self.api.wss_url, on_message=self.on_message, on_error=self.on_error, on_close=self.on_close, on_open=self.on_open)

    def api_dict_clean(self, obj):
        if len(obj) > 5000:
            for k in obj.keys():
                del obj[k]
                break

    def on_message(self, wss, message):
        global_value.ssl_Mutual_exclusion = True
        logger = logging.getLogger(__name__)
        logger.debug(message)
        message = json.loads(str(message))

        # timestamp corretora
        if message["name"] == "timeSync":
            self.api.timesync.server_timestamp = message["msg"]

        #resultado operação digital e binarias
        elif message["name"] == "position-changed":
            if message["microserviceName"] == "portfolio" and (message["msg"]["source"] == "digital-options") or message["msg"]["source"] == "trading":
                self.api.order_async[int(message["msg"]["raw_event"]["order_ids"][0])][message["name"]] = message
            elif message["microserviceName"] == "portfolio" and message["msg"]["source"] == "binary-options":
                self.api.order_async[int(message["msg"]["external_id"])][message["name"]] = message
            else:
                self.api.position_changed = message

        # resultado operação binarias
        elif message["name"] == "socket-option-closed":
            id = message["msg"]["id"]
            self.api.option_closed[id] = message

        # Operação realizada nas binarias
        elif message["name"] == "option":
            self.api.buy_multi_option[str(message["request_id"])] = message["msg"]

        # Operação realizada nas digitais
        elif message["name"] == "digital-option-placed":
            if message["msg"].get("id") != None:
                self.api_dict_clean(self.api.buy_multi_option)
                self.api.buy_multi_option[str(message["request_id"])] = message["msg"]["id"]
            else:
                self.api.buy_multi_option[message["request_id"]] = {
                    "code": "error_place_digital_order",
                    "message": message["msg"]["message"]}
                
        # captura ordens abertas nas binarias          
        elif message['name'] == 'option-opened':
            self.api.orders_opened.append(message['msg'])
        # captura ordens abertas na digital
        elif message['name'] == 'order-changed':
            self.api.orders_opened.append(message['msg'])
        
        # get candles
        elif message['name'] == 'candles':
            try:
                request_id = message["request_id"]
                candles_data = message["msg"]["candles"]
                self.api.candles.add_candles(request_id, candles_data)
                self.api.candles.candles_data = candles_data
            except Exception as e:
                # print(f"Erro ao processar candles: {e}")
                pass

        # candles realtime
        elif message["name"] == "candle-generated":
            active_name = list(OP_code.ACTIVES.keys())[list(OP_code.ACTIVES.values()).index(message["msg"]["active_id"])]
            self.api.all_realtime_candles[active_name] = message["msg"]

        # ativos e payouts turbo e binarias      
        elif message['name'] == "initialization-data": 
            self.api.assets_binarias = message["msg"]

        # payouts digitais
        elif message['name'] == 'top-assets': 
            if message['msg']['instrument_type'] == 'digital-option': 
                self.api.assets_digital = message['msg']['data']

        # ativos abertos digitais
        elif message["name"] == "underlying-list" or message["name"] == "underlying-list-changed":
            self.api.leverage = message
            digital_data = message["msg"]["underlying"]
            lista = {}
            for digital in digital_data:
                active_id = digital['active_id']
                nome_ativo = digital["underlying"]
                enable = digital["is_enabled"]
                suspended = digital["is_suspended"]
                horarios = digital["schedule"]
                lista[nome_ativo] = {}
                if enable == True and suspended ==False:
                    lista[nome_ativo]['open'] = True
                else:
                    lista[nome_ativo]['open'] = False
            self.api.underlying_list = lista

        # saldo das contas
        elif message["name"] == "balances":
            self.api.balances_raw = message

        # profile balances
        elif message["name"] == "profile":
            self.api.profile.msg = message["msg"]
            if self.api.profile.msg != False:
                try:
                    self.api.profile.balance = message["msg"]["balance"]
                except:
                    pass
                # Set Default account
                if global_value.balance_id == None:
                    for balance in message["msg"]["balances"]:
                        if balance["type"] == 4:
                            global_value.balance_id = balance["id"]
                            break
                try:
                    self.api.profile.balance_id = message["msg"]["balance_id"]
                except:
                    pass
                try:
                    self.api.profile.balance_type = message["msg"]["balance_type"]
                except:
                    pass
                try:
                    self.api.profile.balances = message["msg"]["balances"]
                except:
                    pass

        # alertas criados, excluidos, editados                
        elif message["name"] == "alert":
            self.api.alerta = message['msg']
        # alertas tocados
        elif message["name"] == "alert-triggered":
            self.api.alertas_tocados.append(message["msg"])
        # retorna todos os alertas
        elif message["name"] == "alerts":
            self.api.alertas = message['msg']['records']
            
        # abertura ordem forex    
        elif message["name"] == "stop-order-placed":
            self.api.buy_forex_id = message
        # cencela pendente no forex
        elif message["name"] == "pending-order-canceled":
            self.api.cancel_order_forex = message
        # ordens em andamento no forex
        elif message["name"] == "positions":
            self.api.positions_forex= message
        # ordens fechadas no forex
        elif message["name"] == "history-positions":
            self.api.fechadas_forex = message
        # ordens pendentes no forex 
        elif message["name"] == "orders":
            self.api.pendentes_forex = message
        # leverage forex
        elif message["name"] == "available-leverages":
            self.api.available_leverages = message


        global_value.ssl_Mutual_exclusion = False

    @staticmethod
    def on_error(wss, error):
        logger = logging.getLogger(__name__)
        logger.error(error)
        global_value.websocket_error_reason = str(error)
        global_value.check_websocket_error = True

    @staticmethod
    def on_open(wss):
        logger = logging.getLogger(__name__)
        logger.debug("Websocket client connected.")
        global_value.check_websocket_connect = 1

    @staticmethod
    def on_close(wss, close_status_code, close_msg):
        logger = logging.getLogger(__name__)
        logger.debug("Websocket connection closed.")
        global_value.check_websocket_connect = 0
