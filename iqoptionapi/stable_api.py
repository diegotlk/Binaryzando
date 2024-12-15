import json,time
import ssl
import logging
import requests
import threading
from collections import defaultdict
from random import randint
from datetime import datetime, timedelta
from iqoptionapi.expiration import get_expiration_time
import iqoptionapi.constants as OP_code
import iqoptionapi.global_value as global_value
from iqoptionapi.ws.client import WebsocketClient
from iqoptionapi.ws.objects.candles import Candles
from iqoptionapi.ws.objects.profile import Profile
from iqoptionapi.ws.objects.timesync import TimeSync

def nested_dict(n, type):
    if n == 1:
        return defaultdict(type)
    else:
        return defaultdict(lambda: nested_dict(n - 1, type))
    
class IQ_Option(object):
    __version__ = "1.0.2"
    candles = Candles()
    dict_candles = {}
    profile = Profile()
    timesync = TimeSync()
    buy_multi_option = {}
    option_closed = {}
    order_async = nested_dict(2, dict)
    def __init__(self, email, password, active_account_type="PRACTICE", proxies=None):
        self.host = "iqoption.com"
        self.https_url = f"https://{self.host}/api"
        self.url_auth = f"https://auth.{self.host}/api/v2/login"
        self.wss_url = f"wss://{self.host}/echo/websocket"
        self.username = email
        self.password = password
        self.token_2fa = None
        self.codigo_recebido = None
        self.token_code = None
        self.active_account_type = active_account_type
        self.proxies = proxies  
        self.session = requests.Session()
        self.websocket_client = None
        self.underlying_list = None
        self.orders_opened = []
        self.alerta = None
        self.alertas = None
        self.alertas_tocados = []
        self.all_realtime_candles = {}
        #novas funções do forex
        self.buy_forex_id = None
        self.positions_forex= None
        self.fechadas_forex = None
        self.pendentes_forex = None
        self.cancel_order_forex = None
        self.available_leverages = None
        self.leverage= None

    #==========================================================================#
    @property
    def websocket(self):
        return self.websocket_client.wss
    
    def send_websocket_request(self, name, msg, request_id="", no_force_send=True):
        logger = logging.getLogger(__name__)
        data = json.dumps(dict(name=name,msg=msg, request_id=request_id))
        while (global_value.ssl_Mutual_exclusion or global_value.ssl_Mutual_exclusion_write) and no_force_send:
            pass
        global_value.ssl_Mutual_exclusion_write = True
        self.websocket.send(data)
        logger.debug(data)
        global_value.ssl_Mutual_exclusion_write = False
        return str(request_id)

    def websocket_alive(self):
        return self.websocket_thread.is_alive()

    def start_websocket(self):
        try:
            global_value.check_websocket_connect = None
            global_value.check_websocket_error = False
            global_value.websocket_error_reason = None
            self.websocket_client = WebsocketClient(self)
            self.websocket_thread = threading.Thread(target=self.websocket.run_forever, kwargs={'sslopt': {"check_hostname": False, "cert_reqs": ssl.CERT_NONE}})
            self.websocket_thread.daemon = True
            self.websocket_thread.start()
            timeout = 10  # Limite de 10 segundos para conectar
            t_time = time.time()
            while time.time() - t_time < timeout:
                if global_value.check_websocket_error:
                    return False, global_value.websocket_error_reason
                if global_value.check_websocket_connect == 0:
                    return False, "Websocket connection closed."
                elif global_value.check_websocket_connect == 1:
                    return True, None
                time.sleep(0.1) # Segurança contra excesso de envios
            return False, "Tempo excedido ao conectar ao WebSocket."
        except Exception as e:
            print(f"Erro ao conectar ao WebSocket: {e}")
            time.sleep(5)  # Aguarde antes de tentar reconectar

    def close(self):
        self.websocket.close()
        self.websocket_thread.join()

    def get_ssid(self):
        try:
            if self.token_2fa is None:
                data = {"identifier": self.username, "password": self.password}
            else:
                data = {"identifier": self.username, "password": self.password, "token": self.token_2fa}

            headers = {"Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",}
            if "iqop" not in self.url_auth:
                return None 
            else:
                response = self.session.post(self.url_auth, data=json.dumps(data), headers=headers, proxies=self.proxies)
            
            if response.status_code == 200:
                return response
            else:
                return response
        except Exception as e:
            return None

    def send_ssid(self):
        self.profile.msg = None
        self.send_websocket_request(name="ssid", msg=global_value.SSID )
        while self.profile.msg == None:
            pass
        if self.profile.msg == False:
            return False
        else:
            return True

    def get_server_timestamp(self):
        return self.timesync.server_timestamp

    def send_code(self,recebido,metodo, token_reason):
        url_2fa = f"https://auth.{self.host}/api/v2/verify/2fa"
        if recebido:
            data = {"code": str(metodo),
                    "token": token_reason}
        else:
            data = {"method": str(metodo),
                    "token": token_reason}

        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'Referer': f'https://{self.host}/en/login',
            'Sec-Fetch-Mode': 'cors',
            'User-Agent': 'Mozilla/5.0 (Windows NT 6.3; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/77.0.3865.90 Safari/537.36'
            }
        
        response = self.session.post(url_2fa, data=json.dumps(data), headers=headers, proxies=self.proxies)
        return response

    def __2fa(self, token, token_code):
        response = self.send_code(True, token, token_code)
        if response.json()['code'] != 'success':
            return False, response.json()['message']
        self.token_2fa = response.json()['token']
        if self.token_2fa is None:
            return False, None
        return True, None
    
    def connect(self, token = None):
        try:
            self.close()
        except:
            pass
        global_value.ssl_Mutual_exclusion = False
        global_value.ssl_Mutual_exclusion_write = False
        if token == None:
            self.token_2fa = None   
        else: 
            #### chamando função com codigo de autenticação
            status, reason = self.__2fa(token, self.token_code)
            if not status:
                return status, reason

        check_websocket, websocket_reason = self.start_websocket()
        if not check_websocket:
            return check_websocket, websocket_reason
        
        if global_value.SSID == None:
            response = self.get_ssid()
            if not response:
                return False, response.text
            try:
                global_value.SSID = response.cookies["ssid"]
            except (AttributeError, KeyError) as e:
                if json.loads(response.text)['code'] == 'verify':
                    response = self.send_code(False, json.loads(response.text)['method'],json.loads(response.text)['token'])
                    if response.json()['code'] != 'success':
                        return False, response.json()['message']
            
                    self.token_code = response.json()['token']
                    return False, '2FA'
                return False, response.text
            self.start_websocket()
            self.send_ssid()

        requests.utils.add_dict_to_cookiejar(self.session.cookies, {"ssid": global_value.SSID})
        while True:
            try:
                if self.timesync.server_timestamp != None:
                    break
            except:
                pass
        self.change_balance('PRACTICE')
        return True, None
    
    def check_connect(self):
        return global_value.check_websocket_connect is not None
    
    def reconnect(self):
        if not self.check_connect():
            self.close()  # Fechar conexões pendentes
            logging.warning(">>>>>>>>>> ConnectionLost: Starting Reconnect... <<<<<<<<<<")
            self.connect()
    
    @property
    def getprofile(self):
        try:
            url = f"{self.https_url}/getprofile"
            response = self.session.get(url)
            if response.status_code == 200:
                self.profile = response.json()
                return self.profile
            else:
                return None
        except Exception as e:
            return None

    def get_profile(self):
        while self.profile.msg == None:
            pass
        return self.profile.msg
    
    def portfolio(self, Main_Name, name, instrument_type, user_balance_id="", limit=1, offset=0, request_id=""):
        request_id = str(request_id)
        if name == "portfolio.order-changed":
            msg = {"name": name, "version": "1.0", "params": {"routingFilters": {"instrument_type": str(instrument_type)}}}
        elif name == "portfolio.get-positions":
            msg = {"name": name, "version": "3.0", "body": {"instrument_type": str(instrument_type), "limit": int(limit), "offset": int(offset)}}
        elif name == "portfolio.position-changed":
            msg = {"name": name, "version": "2.0", "params": {"routingFilters": {"instrument_type": str(instrument_type),"user_balance_id": user_balance_id}}}
        self.send_websocket_request(name=Main_Name, msg=msg, request_id=request_id)

    def position_change_all(self, Main_Name, user_balance_id):
        instrument_type = ["cfd", "forex", "crypto", "digital-option", "turbo-option", "binary-option"]
        for ins in instrument_type:
            self.portfolio(Main_Name=Main_Name, name="portfolio.position-changed", instrument_type=ins, user_balance_id=user_balance_id)

    def get_balance_mode(self):
        for balance in self.get_profile()["balances"]:
            if balance["id"] == global_value.balance_id:
                if balance["type"] == 1:
                    return "REAL"
                elif balance["type"] == 4:
                    return "PRACTICE"
                elif balance["type"] == 2:
                    return "TOURNAMENT"

    def change_balance(self, Balance_MODE):
        real_id, practice_id, tournament_id = None, None, None
        for balance in self.get_profile()["balances"]:
            if balance["type"] == 1:
                real_id = balance["id"]
            elif balance["type"] == 4:
                practice_id = balance["id"]
            elif balance["type"] == 2:
                tournament_id = balance["id"]
        def set_id(b_id):
            if global_value.balance_id != None:
                self.position_change_all("unsubscribeMessage", global_value.balance_id)
            global_value.balance_id = b_id
            self.position_change_all("subscribeMessage", b_id)
        if Balance_MODE == "REAL":
            set_id(real_id)
        elif Balance_MODE in ["PRACTICE", "DEMO"]:
            set_id(practice_id)
        elif Balance_MODE in ["TOURNAMENT", "TORNEIO"]:
            set_id(tournament_id)
        else:
            logging.error("[**ERROR**] Conta selecionada não é válida! ")

    def get_balance(self):
        try:
            self.balances_raw = None
            data = {"name":"get-balances","version":"1.0"}
            self.send_websocket_request(name="sendMessage", msg=data)
            while self.balances_raw == None:
                pass
            else:
                for balance in self.balances_raw["msg"]:
                    if balance["id"] == global_value.balance_id:
                        return balance["amount"]
            return self.balances_raw
        except Exception as e:
            logging.error(f"[**ERROR**] Obtendo saldo da conta: {e}")
            self.reconnect()

    def get_candles(self, ativo, timeframe, quantidade, timestamp):
        if "-OTC" not in ativo:
            par = ativo + "-op"
            if par not in OP_code.ACTIVES:
                par= ativo
        else:
            par = ativo
        if par not in OP_code.ACTIVES:
            raise ValueError(f'Ativo {par} não encontrado no Constants')
        self.candles.candles_data = None
        while True:
            try:
                data = {"name":"get-candles",
                        "version":"2.0",
                        "body":{"active_id":int(OP_code.ACTIVES[par]),
                                "split_normalization": True,
                                "size":int(timeframe),
                                "to":int(timestamp),   
                                "count":int(quantidade),
                                "":OP_code.ACTIVES[par]}}
                request = str(randint(0, 10000))
                self.send_websocket_request(name="sendMessage", msg=data, request_id=request)

                t_time = time.time()            
                while self.check_connect and request not in self.candles.candles:
                    if time.time() - t_time > 10:
                        raise TimeoutError(f'[**ERROR**] {par}: Aguardando get_candles, reconnect!')
                    time.sleep(0.1) 
                if request in self.candles.candles:
                    break
            except Exception as e:
                self.reconnect()
            time.sleep(1)
        return self.candles.candles.pop(request)

    def __buy_bin(self, valor, ativo, direcao, expiracao):
        exp, idx = get_expiration_time(int(self.timesync.server_timestamp), expiracao)
        if idx < 5:
            option = 3  # "turbo"
        else:
            option = 1  # "binary"
        data ={"name": "binary-options.open-option",
               "version": "1.0",
               "body": {"user_balance_id": int(global_value.balance_id),
                        "active_id": ativo,
                        "option_type_id": option,
                        "direction": direcao.lower(),
                        "expired": int(exp),
                        "price": valor},}
        request_id = str(randint(0, 10000))
        self.send_websocket_request(name="sendMessage", msg=data, request_id=request_id)
        return request_id

    def __buy_digi(self,valor, ativo, direcao, expiracao):
        direction_map = {'put': 'P', 'call': 'C'}
        action = direction_map.get(direcao.lower())
        if not action:
            raise ValueError("Direção inválida! Use 'put' ou 'call'")
        if expiracao == 1:
            exp, _ = get_expiration_time(int(self.timesync.server_timestamp), expiracao)
        else:
            now_date = datetime.fromtimestamp(int(self.timesync.server_timestamp)) + timedelta(minutes=1, seconds=30)
            while True:
                if now_date.minute % expiracao == 0 and time.mktime(now_date.timetuple()) - int(self.timesync.server_timestamp) > 30:
                    break
                now_date = now_date + timedelta(minutes=1)
            exp = time.mktime(now_date.timetuple())
        date_formated = str(datetime.utcfromtimestamp(exp).strftime("%Y%m%d%H%M"))
        instrument_id = f"do{ativo}A{date_formated[:8]}D{date_formated[8:]}00T{expiracao}M{action}SPT"
        data = {"name":"digital-options.place-digital-option",
                "version":"3.0",
                "body":{"user_balance_id": int(global_value.balance_id),
                        "instrument_id": instrument_id,
                        "amount": str(valor),
                        "instrument_index": 0,
                        "asset_id": int(ativo)}}
        request_id = str(randint(0, 10000))
        self.send_websocket_request(name="sendMessage", msg=data, request_id=request_id)
        return request_id

    def buy(self, ativo, valor, direcao, expiracao, tipo_operacao):
        self.reconnect()
        if "-OTC" not in ativo:
            par = ativo + "-op"
            if par not in OP_code.ACTIVES:
                par = ativo
        else:
            par = ativo
        if par not in OP_code.ACTIVES:
            raise ValueError(f'Ativo {par} não encontrado no Constants')
        if tipo_operacao == 'digital':
            req_id = self.__buy_digi(float(valor), OP_code.ACTIVES[ativo], str(direcao), int(expiracao))
            while self.buy_multi_option.get(req_id) is None:
                pass
            order_id = self.buy_multi_option.get(req_id)
            if isinstance(order_id, int):
                return True, order_id
            else:
                return False, order_id     
        else:
            req_id = self.__buy_bin(float(valor), OP_code.ACTIVES[ativo], str(direcao), int(expiracao))
            start_t = time.time()
            while time.time() - start_t < 5:
                if req_id in self.buy_multi_option and "id" in self.buy_multi_option[req_id]:
                    return True, self.buy_multi_option[req_id]["id"]
                elif "message" in self.buy_multi_option.get(req_id, {}):
                    return False, self.buy_multi_option[req_id]["message"]
            return False, self.buy_multi_option
    
    def check_win(self, id, tipo_operacao):
        try:
            self.reconnect()
            if tipo_operacao == 'digital':
                def get_order_data(buy_order_id):
                    while True:
                        order = self.order_async.get(buy_order_id, {})
                        if order.get("position-changed"):
                            return order["position-changed"]["msg"]
                order_data = get_order_data(id)
                if order_data != None:
                    if order_data["status"] == "closed":
                        if order_data["close_reason"] == "expired":
                            return True, order_data["close_profit"] - order_data["invest"]
                        elif order_data["close_reason"] == "default":
                            return True, order_data["pnl_realized"]
                    else:
                        return False, None
                else:
                    return False, None
            else:
                while True:
                    time.sleep(0.05)
                    try:
                        if self.option_closed[id] is not None:
                            break
                    except KeyError:
                        pass
                x = self.option_closed[id]
                return x['msg']['win'], (0 if x['msg']['win'] == 'equal' else float(x['msg']['sum']) * -1 if x['msg']['win'] == 'loose' else float(x['msg']['win_amount']) - float(x['msg']['sum']))
        except Exception as e:
            print(f"Erro em check_win: {e}")
            self.reconnect()

    def __get_binary_open(self):
        try:
            self.reconnect()
            self.assets_binarias = None 
            msg = {"name": "get-initialization-data", "version": "4.0", "body": {}} 
            self.send_websocket_request(name="sendMessage", msg=msg) 
            start = time.time() 
            while self.assets_binarias == None: 
                time.sleep(0.1) 
                if time.time() - start >= 10:		
                    return None 
            binary_data = self.assets_binarias 
            binary_list = ["binary", "turbo"] 
            if binary_data:
                for option in binary_list:
                    if option in binary_data:
                        for actives_id, active in binary_data[option]["actives"].items():
                            try:
                                name = str(active["name"]).split(".")[1]
                                is_enabled = active["enabled"]
                                is_suspended = active["is_suspended"]
                                payout = (100 - int(active["option"]["profit"]["commission"]) if is_enabled and not is_suspended else 0)
                                self.OPEN_TIME[option][name] = {"open": is_enabled and not is_suspended, "payout": payout,}
                                OP_code.ACTIVES[name] = int(actives_id)
                            except Exception as e:
                                # logging.error(f"[**ERROR**] Processing binary asset {actives_id}: {e}")  
                                pass 
                self.update_constants_file()
        except Exception as e:
            print(f"Erro em __get_binary_open: {e}")
            self.reconnect()

    def subscribe_underlying(self):
        digital  = {"name": "digital-option-instruments.get-underlying-list","version": "3.0","body": {"filter_suspended": False}}
        self.send_websocket_request(name="sendMessage", msg=digital)
        subs = {"name":"digital-option-instruments.underlying-list-changed","version":"3.0","params":{"routingFilters":{"is_regulated":False}}}
        self.send_websocket_request(name="subscribeMessage", msg=subs)
        
    def __get_digital_open(self):
        try:
            self.reconnect()
            if self.underlying_list == None:
                self.subscribe_underlying()
                start = time.time()
                while self.underlying_list == None:
                    time.sleep(0.1)
                    if time.time() - start > 10:
                        pass
            self.assets_digital = None 
            msg = {"name":"get-top-assets", "version":"3.0", "body":{"instrument_type":"digital-option", "region_id":-1 }} 
            self.send_websocket_request(name="sendMessage", msg=msg) 
            start = time.time()
            while self.assets_digital is None: 
                if time.time() - start >= 10:
                    return None
                time.sleep(0.5)
                pass
            digital_data = self.assets_digital
            if digital_data:
                for option in digital_data:
                    try:
                        par = list(OP_code.ACTIVES.keys())[list(OP_code.ACTIVES.values()).index(option['active_id'])]
                        payout = int(option.get("spot_profit", 0))
                        self.OPEN_TIME.setdefault("digital", {}).setdefault(par, {"open": False, "payout": 0})
                        try:
                            lista = self.underlying_list
                            try:
                                if lista[par]['open'] ==True:
                                    self.OPEN_TIME["digital"][par]["open"] = True
                                    self.OPEN_TIME["digital"][par]["payout"] = payout
                            except:
                                self.OPEN_TIME["digital"][par]["open"] = False
                                self.OPEN_TIME["digital"][par]["payout"] = 0
                        except:
                            if payout > 0:
                                self.OPEN_TIME["digital"][par]["open"] = True
                                self.OPEN_TIME["digital"][par]["payout"] = payout
                            else:
                                self.OPEN_TIME["digital"][par]["open"] = False
                                self.OPEN_TIME["digital"][par]["payout"] = 0
                    except Exception as e:
                        # logging.error(f"[**ERROR**] Processing digital asset: {e}")  
                        pass
        except Exception as e:
            print(f"Erro em __get_digital_open: {e}")
            self.reconnect()

    def get_profit_all(self):
        self.OPEN_TIME = nested_dict(2, dict)
        binary = threading.Thread(target=self.__get_binary_open)
        digital = threading.Thread(target=self.__get_digital_open)
        binary.start(), digital.start()
        binary.join(), digital.join()
        return json.loads(json.dumps(self.OPEN_TIME))
    
    def update_constants_file(self):
        try:
            with open('iqoptionapi/constants.py', 'r') as f:
                content = f.read()
            if "ACTIVES" in content:
                start_index = content.index("ACTIVES =") + len("ACTIVES =")
                end_index = content.index("}", start_index) + 1 
                formatt = "{"
                for name, actives_id in OP_code.ACTIVES.items():
                    formatt += f"\n    \"{name}\": {actives_id},"
                formatt = formatt.rstrip(',') + "\n}"
                content = content[:start_index] + formatt + content[end_index:]
            else:
                formatt = "{"
                for name, actives_id in OP_code.ACTIVES.items():
                    formatt += f"\n    \"{name}\": {actives_id}," 
                formatt = formatt.rstrip(',') + "\n}"
                content += f"\nACTIVES = {formatt}\n"
            with open('iqoptionapi/constants.py', 'w') as f:
                f.write(content)
        except Exception as e:
            logging.error(f"[**ERROR**] When updating the asset list: {e}")
          
            
    def opened_orders(self):
        return self.orders_opened
    
    def criar_alerta(self, active, instrument_type, value):
        self.alerta = None
        asset_id = OP_code.ACTIVES[active]
        data = {
            "name": "create-alert",
            "version":"1.0",
            "body":{
                "asset_id":int(asset_id),
                "instrument_type":instrument_type,
                "type":"price",
                "value":value,
                "activations":1
                }
        }
        self.send_websocket_request(name="sendMessage", msg=data)
        while self.alerta == None:
            time.sleep(0.01)
            pass   
        return self.alerta

    def start_subscribe_alerts(self):
        name = "subscribeMessage"
        data = {"name": "alert-triggered"}
        self.send_websocket_request(name=name, msg=data)   

    def get_alerta(self):
        self.alertas = None
        data = {
            "name": "get-alerts",
            "version":"1.0",
            "body":{
                "asset_id":0,
                "type":""}}
        self.send_websocket_request(name="sendMessage", msg=data)
        while self.alertas == None:
            time.sleep(0.01)
            pass
        if self.alertas != []:
            for i in self.alertas:
                i['par'] = list(OP_code.ACTIVES.keys())[list(OP_code.ACTIVES.values()).index(i['asset_id'])]
        return self.alertas

    def delete_alerta(self,id):
        self.alerta = None
        data = {
            "name": "delete-alert",
            "version":"1.0",
            "body":{"id":id}}
        self.send_websocket_request(name="sendMessage", msg=data) 

        while self.alerta == None:
            time.sleep(0.01)
            pass            
        return self.alerta
    
    def alertas_realtime(self):
        return self.alertas_tocados
    
    def start_candles_stream(self,ativo,size):
        asset_id = OP_code.ACTIVES[ativo]
        name = "subscribeMessage"
        data = {"name": "candle-generated",
                "params": {
                    "routingFilters": {
                        "active_id": str(asset_id),
                        "size": int(size)
                    } }}
        self.send_websocket_request(name=name, msg=data)

    def get_all_realtime(self):
        #primeiro você precisa dar um subscrible no par que deseja
        #usando a função start_candles_stream(ativo,size)
        return self.all_realtime_candles


    def leverage_marginal_forex(self, par):
        self.leverage = None
        data = {"name": "marginal-forex-instruments.get-underlying-list",
        "version": "1.0",
        "body": {}}
        self.send_websocket_request(name="sendMessage", msg=data) 
        while self.leverage == None:
            time.sleep(0.3)
            pass     
        leverage =  self.leverage
        try:
            for i in leverage["msg"]['items']:
                if par in i['name']:
                    leverage = i['max_leverages']['0']
            return leverage
        except:
            return None

    def buy_marginal_forex(self, par,direcao,valor_entrada,preco_entrada,win,lose):
        self.buy_forex_id = None
        leverage = self.leverage_marginal_forex(par)
        par = OP_code.ACTIVES[par]
        data = {
        "name": "marginal-forex.place-stop-order",
        "version": "1.0",
        "body": {
            "side": str(direcao),
            "user_balance_id": int(global_value.balance_id),
            "count": str(valor_entrada),
            "instrument_id": "mf."+str(par),
            "instrument_active_id": int(par),
            "leverage": str(leverage),
            "stop_price": str(preco_entrada),
            "take_profit": {
            "type": "price",
            "value": str(win)
            },
            "stop_loss": {
            "type": "price",
            "value": str(lose)
            } }}
        self.send_websocket_request(name="sendMessage", msg=data) 
        while self.buy_forex_id == None:
            time.sleep(0.3)
            pass
        if self.buy_forex_id["status"] == 2000:
            return True, self.buy_forex_id["msg"]["id"]
        else:
            return False, self.buy_forex_id["msg"]

    def leverage_forex(self, instrument_type, actives):
        self.available_leverages = None
        data = {
            "name":"get-available-leverages",
            "version":"2.0",
            "body":{
                "instrument_type":instrument_type,
                "actives":OP_code.ACTIVES[actives]}}
        self.send_websocket_request(name="sendMessage", msg=data) 

        while self.available_leverages == None:
            pass
        if self.available_leverages["status"] == 2000:
            return True, self.available_leverages["msg"]
        else:
            return False, None
        
    def buy_forex(self, par,direcao,valor_entrada,multiplicador= None,preco_entrada= None,preco_profit= None,preco_lose= None):
        if direcao =='call':
            direcao = 'buy'
        if direcao =='put':
            direcao = 'sell'
              
        if preco_entrada == None:
            tipo = 'market'
        else: tipo = 'limit'
        if preco_lose == None:
            auto_margin = True
        else: auto_margin = False

        if multiplicador == None:
            st, msg = self.leverage_forex("forex",par)
            if st == True:
                multiplicador = msg['leverages'][-1]['regulated_default']
            else: multiplicador = 100

        data = {
        "name": "place-order-temp",
        "version": "4.0",
        "body": {
            "user_balance_id": int(global_value.balance_id),
            "client_platform_id": 9,
            "instrument_type": "forex",
            "instrument_id": str(par),
            "side": str(direcao),
            "type": str(tipo), #"market"/"limit"/"stop"
            "amount": float(valor_entrada),
            "leverage": int(multiplicador),
            "limit_price": preco_entrada, #funciona somente se type="limit"
            "stop_price": 0, #funciona somente se type="stop"
            "auto_margin_call": bool(auto_margin), #true se não estiver usando stop definido
            "use_trail_stop": "false",
            "take_profit_value": preco_profit,
            "take_profit_kind": "price",
            "stop_lose_value": preco_lose,
            "stop_lose_kind": "price"}}
        self.send_websocket_request(name="sendMessage", msg=data) 

        while self.buy_forex_id == None:
            pass
        check, data = self.get_order(self.buy_order_id)
        while data["status"] == "pending_new":
            check, data = self.get_order(self.buy_order_id)
            time.sleep(1)

        if check:
            if data["status"] != "rejected":
                return True, self.buy_order_id
            else:
                return False, data["reject_status"]
        else:

            return False, None

    def cancel_marginal_forex(self, id):
        self.cancel_order_forex = None
        data = {
        "name": "marginal-forex.cancel-pending-order",
        "version": "1.0",
        "body": {
            "order_id": id}}
        self.send_websocket_request(name="sendMessage", msg=data)
        while self.cancel_order_forex == None:
            time.sleep(0.3)
            pass
        if self.cancel_order_forex["status"] == 2000:
            return True, self.cancel_order_forex["msg"]
        else:
            return False, self.cancel_order_forex["msg"]
             
    def get_fechadas_marginal_forex(self):
        self.fechadas_forex= None
        user_id = self.get_profile()['user_id']
        data = {
            "name": "portfolio.get-history-positions",
            "version": "2.0",
            "body": {
                "user_id": user_id,
                "user_balance_id": int(global_value.balance_id),
                "instrument_types": [
                "marginal-forex"
                ],
                "offset": 0,
                "limit": 30 }}
        self.send_websocket_request(name="sendMessage", msg=data)
        while self.fechadas_forex == None:
            time.sleep(0.5)
            pass
        if self.fechadas_forex["status"] == 2000:
            return True, self.fechadas_forex["msg"]
        else:
            return False, self.fechadas_forex["msg"]
    
    def get_positions_marginal_forex(self):
        self.positions_forex= None
        data = {
                "name": "portfolio.get-positions",
                "version": "4.0",
                "body": {
                "offset": 0,
                "limit": 100,
                "user_balance_id": int(global_value.balance_id),
                "instrument_types": [
                    "marginal-forex",
                    "marginal-cfd",
                    "marginal-crypto"]}}
        self.send_websocket_request(name="sendMessage", msg=data) 
        while self.positions_forex== None:
            time.sleep(0.5)
            pass
  
        if self.positions_forex["status"] == 2000:
            return True, self.positions_forex["msg"]
        else:
            return False, self.positions_forex["msg"]

    def get_pendentes_forex(self):
        self.pendentes_forex= None
        data = {
                "name": "portfolio.get-orders",
                "version": "2.0",
                "body": {
                    "user_balance_id": int(global_value.balance_id),
                    "kind": "deferred"}}
        self.send_websocket_request(name="sendMessage", msg=data) 
        while self.pendentes_forex== None:
            time.sleep(0.5)
            pass
        if self.pendentes_forex["status"] == 2000:
            return True, self.pendentes_forex["msg"]
        else:
            return False, self.pendentes_forex["msg"]
