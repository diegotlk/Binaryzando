from iqoptionapi.stable_api import IQ_Option
from datetime import datetime
from configobj import ConfigObj
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext
from telebot import TeleBot, types, apihelper
from iqoptionapi.constants import ACTIVES
import numpy as np
import pandas as pd
import pandas_ta as ta
import time
import os
import threading

config = ConfigObj('token.txt')
CHAVE_API = config['token']
bot = TeleBot(CHAVE_API)

executando=False
par=None
tipo=None
lista_negra = [] 
maior_perda = []
lock = threading.Lock()
lucro_total=0
lucro_acumulado=0
resultado=0
vitorias=0
derrotas=0
entrada=0
win=0
loss=0
max_loss=0
max_win=0
pay=0
dpontos=0
gpontos=0
exp = 1
timeframe = 60
qnt_velas = 30


def tentar_reconectar():
    global API
    while not API.check_connect():
        print("Tentando reconectar...")
        API.connect()
        time.sleep(5)

def calcular_ema(API, df, timeframe, periodo=25):
    ema = df['close'].ewm(span=periodo, adjust=False).mean()
    return ema.iloc[-1] if not ema.empty else 0

def calcular_rsi(df, periodo=4):
    return round(ta.rsi(df['close'], length=periodo).iloc[-1])

def calcular_fractal(df):
    max_atual = df.iloc[1]['high']
    max_vizinhos = max(df.iloc[0]['high'],df.iloc[2]['high'])
    fractal_up = max_atual > max_vizinhos and max_atual > df.iloc[1]['close']

    min_atual = df.iloc[1]['low']
    min_vizinhos = min(df.iloc[0]['low'],df.iloc[2]['low'])
    fractal_down = min_atual < min_vizinhos and min_atual < df.iloc[1]['close']

    return fractal_up, fractal_down

def obter_velas(API, par, qnt_velas, timeframe):
    try:
        velas = API.get_candles(par, timeframe, qnt_velas, time.time())
        if not velas:  
            print(f"Erro: Nenhum dado retornado para {par}.")
            return None
        return pd.DataFrame({
            'timestamp': [vela['from'] for vela in velas],
            'open': [vela['open'] for vela in velas],
            'close': [vela['close'] for vela in velas],
            'low': [vela['min'] for vela in velas],
            'high': [vela['max'] for vela in velas]
        })
    except Exception as e:
        print(f"Erro ao obter velas para {par}: {e}")
        return None

def maior_payout():
    global lista_negra
    payouts = {}

    try:
        pays = API.get_profit_all()
    except:
        return None

    for tipo in ['turbo', 'digital']:
        if tipo not in pays:
            continue

        for par in pays[tipo]:
            if par not in payouts:
                payouts[par] = {}

            status = 'aberto' if pays[tipo][par]['open'] else 'fechado'
            payouts[par][tipo] = {
                'status': status,
                'payout': pays[tipo][par]['payout']
            }

    table_data = []

    for par, values in payouts.items():
        if par in lista_negra:
            continue

        digital_status = values.get('digital', {}).get('status', 'fechado')
        turbo_status = values.get('turbo', {}).get('status', 'fechado')

        if digital_status == 'fechado' or turbo_status == 'fechado':
            continue  

        digital_payout = values.get('digital', {}).get('payout', 0)
        turbo_payout = values.get('turbo', {}).get('payout', 0)
        melhor_tipo = 'digital' if digital_payout >= turbo_payout else 'turbo'

        table_data.append([
            par,
            max(digital_payout, turbo_payout),
            melhor_tipo,
            digital_status,
            turbo_status
        ])

    table_data.sort(key=lambda x: x[1], reverse=True)

    return table_data[0] if table_data else None

def main_loop():
    global executando, lista_negra, par, dpontos, gpontos, pay, tipo,win
    executando = True

    while executando:
        time.sleep(0.1)
        try:
            if not API.check_connect():
                tentar_reconectar()

            if win == 0:
                resul = maior_payout()
                par = resul[0] 
                pay = resul[1] 
                tipo = resul[2] 
                lista_negra.append(par)

            df = obter_velas(API, par, qnt_velas, timeframe)  
            rsi = calcular_rsi(df)
            print(f"RSI: {rsi}", end="\r")
            if 20 < rsi < 80:
                fractal_up, fractal_down = calcular_fractal(df)
                ema = calcular_ema(API, df, timeframe)            
                preco = df['close'].iloc[-1]
                                 
                if rsi < 80 and preco > ema and not fractal_up:
                    gsinal = "put"
                    dsinal = "call"

                    if abs(dpontos - gpontos) > 1: 
                        if gpontos < dpontos:
                            direcao = "call"
                        else:
                            direcao = "put"
                    else:
                        direcao = "put"

                elif rsi > 20 and preco < ema and not fractal_down:
                    gsinal = "call"
                    dsinal = "put"
                    
                    if abs(dpontos - gpontos) > 1: 
                        if gpontos < dpontos:
                            direcao = "put"
                        else:
                            direcao = "call"
                    else:
                        direcao = "call"

                else:
                    direcao = None

                if direcao:
                    bot.send_message(chat_id,
                        '------------------------\n'
                        f"🔅 Entrada encontrada !!\n"
                        f"{par} | {pay}%\n"
                        f"D.{dpontos} x G.{gpontos}\n")
                    
            else:
                direcao = None

            if direcao:
                entrar = entradas(par, direcao, tipo, pay)

                atualizar_pontuacao(par, dsinal, gsinal)

                if lucro_total > 0:
                    painel_final = estatistica()

        except Exception as e:
            import traceback
            print(f"Erro: {e}")
            traceback.print_exc()

def atualizar_pontuacao(par, dsinal, gsinal):
    global dpontos, gpontos, resultado

    try:
        if resultado != 0:
            while True:
                velas = API.get_candles(par, timeframe, 1, time.time())
                if not velas or len(velas) == 0:
                    print("Erro: Dados de vela não encontrados.")
                    time.sleep(1) 
                    continue

                vela = velas[0]
                if 'open' not in vela or 'close' not in vela or 'from' not in vela:
                    print("Erro: Estrutura de vela inválida.")
                    time.sleep(1) 
                    continue

                horario_abertura = datetime.fromtimestamp(vela['from']).strftime("%H:%M:%S")

                break

            if vela['open'] > vela['close']:
                dir = "put"
                
            elif vela['open'] < vela['close']:
                dir = "call"
            else:
                dir = None
            
            with lock:
                if dir == dsinal:
                    dpontos += 1
                else:
                    dpontos -= 1

                if dir == gsinal:
                    gpontos += 1
                else:
                    gpontos -= 1

                if dpontos < 0:
                    dpontos = 0
                if gpontos < 0:
                    gpontos = 0

    except Exception as e:
        print(f"Erro ao atualizar pontuação: {e}")

def entradas(par,direcao,tipo,pay):
    global executando
    entrada = calculo_entrada(pay)
    while executando:
        time.sleep(0.1)
        segundos = float(datetime.fromtimestamp(API.get_server_timestamp()).strftime('%S'))

        if segundos in [58]: 
            compra(par, direcao, exp, tipo, entrada)
            return

def calculo_entrada(pay):
    global lucro_total, resultado,loss,entrada
    pay2 = pay / 100
    saldo = float(API.get_balance())
    sdo = 2

    if loss >1:
        if resultado < 0:
            entrada = (abs(lucro_total) - sdo) / pay2
            
        elif resultado > 0:
            entrada = abs(lucro_total) * 2
    else:
        entrada=abs(lucro_total) * 2

    entrada = round(max(entrada, 2), 2)

    if entrada >= 100:
        bot.send_message(chat_id, '❌')
        bot.send_message(chat_id,"❌  Stop Loss Atingido")
        os._exit(0)

    return entrada

def compra(par, direcao, exp, tipo, entrada):
    global executando, lucro_total, resultado, vitorias, derrotas, lista_negra
    global win, loss, max_loss, max_win

    try:
        horario_entrada = datetime.fromtimestamp(API.get_server_timestamp()).strftime("%H:%M:%S")

        if tipo == "digital":
            check, id = API.buy(par,entrada,direcao,exp,'digital')
        else:
            check, id = API.buy(par,entrada,direcao,exp,'binary')

        if check:
            bot.send_message(chat_id, 
                '------------------------\n'
                f'🔔 Ordem Aberta | {direcao}\n'                
                f'🪙 Par: {par}\n'
                f'💵 Entrada: R$ {round(entrada, 2)}\n'
                f'⏰ Horário: {horario_entrada}\n')

            while executando:
                time.sleep(0.01)
                if tipo == "digital":
                    status , resultado = API.check_win(id,'digital')
                else:
                    status , resultado = API.check_win(id,'binary')

                if status:
                    lucro_total += round(resultado, 2)

                    if resultado > 0: 
                        vitorias += 1
                        win += 1
                        loss = 0 
                        if win > max_win:
                            max_win = win

                        bot.send_message(chat_id, '✅')
                        bot.send_message(chat_id, 
                            f'✅  >>  WIN  <<\n'
                            '------------------------\n'
                            f'🤑  Lucro: R$ {round(resultado, 2)}\n'
                            f'💵  Lucro Total: R$ {round(lucro_total, 2)}\n'
                            f'💰  Saldo: R$ {round(API.get_balance(), 2)}\n')

                    elif resultado == 0:  
                        bot.send_message(chat_id, '🔄')
                        bot.send_message(chat_id, 
                            f'🔄  >>  EMPATE  <<\n'
                            '------------------------\n'
                            f'💵  Lucro Total: R$ {round(lucro_total, 2)}\n'
                            f'💰  Saldo: R$ {round(API.get_balance(), 2)}\n')

                    elif resultado < 0:  
                        derrotas += 1
                        loss += 1
                        win = 0  
                        if loss > max_loss:
                            max_loss = loss

                        armazenar_prejuizo()
                        bot.send_message(chat_id, '❌')
                        bot.send_message(chat_id, 
                            f'❌  >>  LOSS  <<\n'
                            '------------------------\n'
                            f'🔻  Prejuízo: R$ {round(resultado, 2)}\n'
                            f'💵  Lucro Total: R$ {round(lucro_total, 2)}\n'
                            f'💰  Saldo: R$ {round(API.get_balance(), 2)}\n')

                        lista_negra.append(par)

                    break

    except Exception as e:
        print(f"Erro Compra: {e}, tipo: {tipo}, par: {par}, entrada: {entrada}, direcao: {direcao}")
        return

def estatistica():
    global executando, vitorias, derrotas, resultado, lucro_total,lista_negra
    global lucro_acumulado, inicio_execucao, conta_selecionada, max_loss, max_win

    tempo_execucao = time.time() - inicio_execucao
    horas = int(tempo_execucao // 3600)
    minutos = int((tempo_execucao % 3600) // 60)

    armazenar_lucro(lucro_total)
    saldo = float(API.get_balance())
    maior_loss = armazenar_prejuizo()
    assertividade = taxa_acerto()
    lucro_percentual = (lucro_acumulado / saldo) * 100 if saldo > 0 else 0

    bot.send_message(chat_id, "🏆")
    bot.send_message(chat_id, "📊 Painel de Estatísticas 📊")

    if horas > 0:
        tempo_formatado = f"{horas}h {minutos}min"
    else:
        tempo_formatado = f"{minutos}min"

    bot.send_message(chat_id,
        '------------------------\n'           
        f'⏱  Tempo de Execução: {tempo_formatado}\n'
        f'💰  Saldo: R$ {round(saldo, 2)}\n'
        f'🏆  Vitórias: {vitorias} | Seq: {max_win}\n'
        f'🛑  Derrotas: {derrotas} | Seq: {max_loss}\n'
        f'🔻  Maior Loss: R$ {round(maior_loss,2)}\n'
        f'🎯  Assertividade: {round(assertividade)}%\n'
        f'💵  Lucro Real: R$ {round(lucro_acumulado, 2)}\n'
        f'✳   Lucro Percentual: {round(lucro_percentual, 2)}%\n'
    )
    
    lucro_total=0
    resultado=0
    lista_negra.clear()
    if conta_selecionada == 'REAL':
        executando = False
        responder_fake()

def taxa_acerto():
    global vitorias, derrotas
    
    if vitorias + derrotas > 0:
        assertividade = (vitorias * 100) / (vitorias + derrotas)
    else:
        assertividade = 0

    return assertividade

def armazenar_lucro(lucro_total):
    global lucro_acumulado
    if lucro_total > 0:
        lucro_acumulado += lucro_total
        return True
    return False

def armazenar_prejuizo():
    global lucro_total, maior_perda
    maior_perda.append(lucro_total)
    menor_prejuizo = round(min(maior_perda),2)    
    return menor_prejuizo  
        
def responder_fake():
    global chat_id
    bot.send_message(chat_id, "Escolha um dos comandos:", reply_markup=criar_markup())

def iniciar_conexao(message):
    global API, executando, inicio_execucao, lucro_acumulado, conta_selecionada

    config = ConfigObj('log.txt')
    email, senha = config['LOGIN']['email'], config['LOGIN']['senha']
    bot.send_message(message.chat.id, "🤖 Iniciando conexão...")

    API = IQ_Option(email, senha)
    check, reason = API.connect()

    if check:
        inicio_execucao = time.time()
        executando = True
        conta_selecionada = None  
        solicitar_conta(message)
    else:
        bot.send_message(message.chat.id, f"❌ Houve um problema na conexão: {reason}")
        tentar_reconectar(message.chat.id, message)

def solicitar_conta(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("Demo", callback_data='1'),
        types.InlineKeyboardButton("Real", callback_data='2')
    )
    bot.send_message(message.chat.id, "Qual conta você gostaria de usar?", reply_markup=markup)

def selecionar_conta(call):
    global executando, conta_selecionada, lucro_total, lucro_acumulado, resultado
    global vitorias, derrotas, entrada, win, pay, loss
    executando = False
    try:
        bot.answer_callback_query(call.id)
    except Exception as e:
        print(f"Erro callback: {e}")
        return

    conta_selecionada = 'PRACTICE' if call.data == '1' else 'REAL'
    change_balance(conta_selecionada)
    saldo = float(API.get_balance())

    bot.send_message(
        call.message.chat.id, 
        f"------------------------\n✅  Conta {'Demo' if call.data == '1' else 'Real'} Selecionada!"
    )
    
    if not API.check_connect():
        API.reconnect()

    saldo = float(API.get_balance())
    bot.send_message(call.message.chat.id, f"💰  Saldo: R$ {saldo}")

    lucro_total=0
    lucro_acumulado=0
    resultado=0
    vitorias=0
    derrotas=0
    entrada=0
    win=0
    pay=0
    loss=0

    executando = True
    if executando:
        main_loop()

def change_balance(account_type):
    if account_type not in ['PRACTICE', 'REAL']:
        raise ValueError("Tipo de conta inválido. Use 'PRACTICE' ou 'REAL'.")
    API.change_balance(account_type)

def start_command(message):
    global chat_id
    chat_id = message.chat.id
    iniciar_conexao(message)

def pausar(message):
    global executando
    executando = False

    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("🔄 Mudar Conta", callback_data='mudar_conta'),
        types.InlineKeyboardButton("🔒 Travar Bot", callback_data='travar')
    )
    bot.send_message(message.chat.id, "O bot está pausado. Escolha uma opção:", reply_markup=markup)

def mudar_conta(call):
    global executando
    executando = False
    bot.answer_callback_query(call.id)
    solicitar_conta(call.message)

def travar(call):
    global executando
    executando = False
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, "🔒 O bot foi travado. Reinicie para usar novamente.")
    os._exit(0)

def criar_markup():
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("▶  Start", callback_data='start'),
        types.InlineKeyboardButton("⏩  Continue", callback_data='continue'),
        types.InlineKeyboardButton("⏸  Config", callback_data='config')
    )
    return markup

def handle_button_click(call):
    if call.data == 'start':
        start_command(call.message)
    elif call.data == 'continue':
        bot.send_message(call.message.chat.id, "Continuando...")
        main_loop()
    elif call.data == 'config':
        pausar(call.message)
    elif call.data == 'mudar_conta':
        mudar_conta(call)
    elif call.data == 'travar':
        travar(call)

    try:
        bot.answer_callback_query(call.id)
    except Exception as e:
        print(f"Erro callback: {e}")
        return

@bot.callback_query_handler(func=lambda call: call.data in ['start', 'continue', 'config', 'mudar_conta', 'travar'])
def callback_handle_button(call):
    handle_button_click(call)

@bot.callback_query_handler(func=lambda call: call.data in ['1', '2'])
def callback_selecionar_conta(call):
    selecionar_conta(call)

@bot.message_handler(commands=["start"])
def comando_start(message):
    start_command(message)

@bot.message_handler(commands=["config"])
def comando_config(message):
    pausar(message)

@bot.message_handler(func=lambda message: True)
def responder(message):
    bot.reply_to(message, "Escolha um dos comandos:", reply_markup=criar_markup())

if __name__ == '__main__':
    while True:
        try:
            print("Bot iniciando polling...")
            bot.polling(none_stop=True, interval=5, timeout=60)
        except Exception as e:
            print(f"Erro no bot: {e}. Reiniciando em 5 segundos...")
            time.sleep(5)
