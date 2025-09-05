import socket
import threading
import time

# ================================
# Configurações gerais
# ================================
HOST = "0.0.0.0"          # Escuta em todas as interfaces
PORTA_TCP = 5000          # Porta TCP (mensagens de aplicação/controle + Lamport + Ricart-Agrawala)
PORTA_UDP = 5001          # Porta UDP (Berkeley)
TIMEOUT_TCP = 5.0         # Tempo padrão para operações TCP (segundos)
TIMEOUT_UDP = 2.0         # Tempo de espera para respostas UDP (segundos)

# ================================
# Estado de usuários e transações
# ================================
saldo_usuarios = {}                # {usuario: saldo}
usuarios_logados = {}              # {usuario: True/False}
usuarios_senhas = {                # Usuários e senhas fixos
    "Jair": "1234",
    "Professor": "abcd",
    "Aluno": "0000"
}
transacoes_confirmadas = []        # Histórico de transações (strings com timestamp legível)

# ================================
# Estado de hosts e ip distribuído
# ================================
maquinas = set()     # IPs participantes do sistema
meu_ip = None                       

# Relógio lógico de Lamport
relogio_lamport = 0

# Ricart–Agrawala (gerenciamento de região crítica da lista de máquinas)
ra_solicitando = False             # Se esta máquina está solicitando RC
ra_timestamp_solicitacao = None    # Timestamp Lamport da solicitação
ra_respostas_necessarias = 0       # Contador de respostas pendentes
ra_adicionados_posteriormente = set()  # Conjunto de IPs que ficaram pendentes
ra_evento = threading.Event()      # Sinaliza quando todas as réplicas aprovaram

# Berkeley (ajuste de relógio físico "virtual")
deslocamento_relogio = 0.0        

trava = threading.Lock()  # Protege estados locais (saldo, histórico, lista, Lamport etc.)

usuario_logado = None

# ================================
# Utilitários
# ================================
def obter_ip_local():
    """Descobre o IP local preferível para saída."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return socket.gethostbyname(socket.gethostname())

def agora_legivel():
    """Timestamp Formatado (para logs e histórico)."""
    return time.strftime("%Y-%m-%d %H:%M:%S")

def incrementar_lamport_evento():
    """Incrementa Lamport e retorna valor do relógio ."""
    global relogio_lamport
    with trava:
        relogio_lamport += 1 # Incrementa em 1 
        return relogio_lamport

def atualizar_lamport_recebido(ts_msg):
    """Atualiza Lamport ao receber mensagem com timestamp lógico."""
    global relogio_lamport
    with trava:
        relogio_lamport = max(relogio_lamport, ts_msg) + 1
        return relogio_lamport

def tempo_virtual():
    """Retorna 'tempo físico' virtual (time.time + offset do Berkeley)."""
    with trava:
        return time.time() + deslocamento_relogio

def sou_coordenador():
    """Coordenador do Berkeley = primeiro IP da lista."""
    with trava:
        if not maquinas:
            return False
        return meu_ip == sorted(maquinas)[0]

# ================================
# Envio TCP (com Lamport embutido)
# ================================
def enviar_mensagem_tcp(ip, mensagem_sem_ts):
    """Envia mensagem TCP incluindo Lamport no final: '<msg> <lamport>'."""
    if ip == meu_ip:
        return
    ts = incrementar_lamport_evento()
    carga = f"{mensagem_sem_ts} {ts}"
    try:
        with socket.create_connection((ip, PORTA_TCP), timeout=TIMEOUT_TCP) as cliente:
            cliente.sendall(carga.encode("utf-8"))
            try:
                cliente.settimeout(TIMEOUT_TCP)
                cliente.recv(1024)
            except socket.timeout:
                pass
    except Exception as e:
        print(f"[TCP] Falha ao enviar para {ip}: {e}")

def broadcast_tcp(mensagem_sem_ts, excluir=None):
    """Envia para todos da lista de máquinas (exceto a si mesmo)."""
    with trava:
        destinos = list(maquinas)
    for ip in destinos:
        if ip == meu_ip or (excluir and ip == excluir):
            continue
        enviar_mensagem_tcp(ip, mensagem_sem_ts)

# ================================
# Ricart–Agrawala (RC distribuída)
# ================================
def ra_entrar_rc():
    """Solicita entrada na região crítica distribuída."""
    global ra_solicitando, ra_timestamp_solicitacao, ra_respostas_necessarias
    with trava:
        ra_solicitando = True
        ra_timestamp_solicitacao = incrementar_lamport_evento()
        outros = [ip for ip in maquinas if ip != meu_ip]
        ra_respostas_necessarias = len(outros)
        ra_evento.clear()

    if ra_respostas_necessarias == 0:
        return

    msg = f"RA_REQUEST {ra_timestamp_solicitacao} {meu_ip}"
    broadcast_tcp(msg)

    ra_evento.wait(timeout=10.0)

def ra_sair_rc():
    """Libera a RC distribuída e responde pendentes."""
    global ra_solicitando, ra_timestamp_solicitacao, ra_respostas_necessarias
    with trava:
        ra_solicitando = False
        ra_timestamp_solicitacao = None
        ra_respostas_necessarias = 0
        pendentes = list(ra_adicionados_posteriormente)
        ra_adicionados_posteriormente.clear()

    for ip in pendentes:
        enviar_mensagem_tcp(ip, f"RA_REPLY {meu_ip}")

    broadcast_tcp(f"RA_RELEASE {meu_ip}")

def tratar_ra_request(ts_str, ip_remetente):
    """Trata pedido RA_REQUEST recebido."""
    try:
        ts_req = int(ts_str)
    except:
        ts_req = incrementar_lamport_evento()
    atualizar_lamport_recebido(ts_req)

    with trava:
        estou_solicitando = ra_solicitando
        minha_chave = (ra_timestamp_solicitacao if ra_timestamp_solicitacao is not None else float("inf"), meu_ip)
        chave_req = (ts_req, ip_remetente)

        if (not estou_solicitando) or (chave_req < minha_chave):
            responder_imediato = True
        else:
            responder_imediato = False
            ra_adicionados_posteriormente.add(ip_remetente)

    if responder_imediato:
        enviar_mensagem_tcp(ip_remetente, f"RA_REPLY {meu_ip}")

def tratar_ra_reply(ip_remetente):
    """Conta uma resposta RA_REPLY recebida."""
    incrementar_lamport_evento()
    global ra_respostas_necessarias
    with trava:
        if ra_respostas_necessarias > 0:
            ra_respostas_necessarias -= 1
            if ra_respostas_necessarias == 0:
                ra_evento.set()

# ================================
# Berkeley (UDP)
# ================================
def listener_udp():
    """Thread que recebe mensagens UDP do Berkeley."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((HOST, PORTA_UDP))
    while True:
        try:
            dados, endereco = sock.recvfrom(1024)
            msg = dados.decode("utf-8").strip()
            partes = msg.split()
            if not partes:
                continue
            tipo = partes[0]

            if tipo == "BERKLEY_POLL":
                t_local = tempo_virtual()
                resposta = f"BERKLEY_REPLY {meu_ip} {t_local}"
                sock.sendto(resposta.encode("utf-8"), endereco)

            elif tipo == "BERKLEY_ADJUST":
                try:
                    delta = float(partes[1])
                except:
                    delta = 0.0
                with trava:
                    global deslocamento_relogio
                    deslocamento_relogio += delta
                print(f"[Berkeley] Ajuste aplicado: {delta:+.6f}s. Novo offset: {deslocamento_relogio:+.6f}s")

            elif tipo == "BERKLEY_START":
                if sou_coordenador():
                    rodada_berkeley()

        except Exception as e:
            print(f"[UDP] Erro no listener: {e}")

def enviar_udp(ip, mensagem):
    if ip == meu_ip:
        return
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(mensagem.encode("utf-8"), (ip, PORTA_UDP))
        sock.close()
    except Exception as e:
        print(f"[UDP] Falha ao enviar para {ip}: {e}")

def rodada_berkeley():
    with trava:
        destinos = [ip for ip in maquinas if ip != meu_ip]

    if not destinos:
        print("[Berkeley] Sem nós remotos para sincronizar.")
        return

    for ip in destinos:
        enviar_udp(ip, "BERKLEY_POLL")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((meu_ip, 0))
    sock.settimeout(TIMEOUT_UDP)

    respostas = []
    t_coord_ref = tempo_virtual()
    t_inicio = time.time()

    while True:
        try:
            dados, endereco = sock.recvfrom(1024)
            partes = dados.decode("utf-8").split()
            if len(partes) == 3 and partes[0] == "BERKLEY_REPLY":
                try:
                    respostas.append(float(partes[2]))
                except:
                    pass
        except socket.timeout:
            break
        if time.time() - t_inicio > TIMEOUT_UDP + 0.5:
            break

    sock.close()

    if not respostas:
        print("[Berkeley] Nenhuma resposta recebida.")
        return

    medias = [t - t_coord_ref for t in respostas]
    ajuste = sum(medias) / len(medias)

    with trava:
        global deslocamento_relogio
        deslocamento_relogio += ajuste
    print(f"[Berkeley] Coordenador aplicou offset {ajuste:+.6f}s. Novo offset local: {deslocamento_relogio:+.6f}s")

    for ip in destinos:
        enviar_udp(ip, f"BERKLEY_ADJUST {-ajuste}")

def disparar_berkeley():
    if sou_coordenador():
        rodada_berkeley()
    else:
        with trava:
            coord = sorted(maquinas)[0] if maquinas else None
        if coord and coord != meu_ip:
            enviar_udp(coord, "BERKLEY_START")
        else:
            print("[Berkeley] Não há coordenador definido.")

# ================================
# Protocolo de controle de cluster
# ================================
def processar_mensagem_controle(partes, endereco):
    if not partes:
        return
    comando = partes[0]

    if comando == "RA_REQUEST" and len(partes) >= 3:
        ts_req = partes[1]
        ip_req = partes[2]
        try:
            ts_msg = int(partes[-1])
        except:
            ts_msg = incrementar_lamport_evento()
        atualizar_lamport_recebido(ts_msg)
        tratar_ra_request(ts_req, ip_req)

    elif comando == "RA_REPLY" and len(partes) >= 2:
        try:
            ts_msg = int(partes[-1])
        except:
            ts_msg = incrementar_lamport_evento()
        atualizar_lamport_recebido(ts_msg)
        ip_from = partes[1]
        tratar_ra_reply(ip_from)

    elif comando == "RA_RELEASE" and len(partes) >= 2:
        try:
            ts_msg = int(partes[-1])
        except:
            ts_msg = incrementar_lamport_evento()
        atualizar_lamport_recebido(ts_msg)

    elif comando == "JOIN_REQUEST" and len(partes) >= 2:
        ip_novo = partes[1]
        try:
            ts_msg = int(partes[-1])
        except:
            ts_msg = incrementar_lamport_evento()
        atualizar_lamport_recebido(ts_msg)

        ra_entrar_rc()
        try:
            with trava:
                if ip_novo not in maquinas:
                    maquinas.add(ip_novo)
                    maquinas.add(meu_ip)
                lista = ",".join(sorted(maquinas))
            enviar_mensagem_tcp(ip_novo, f"MACHINE_LIST {lista}")
            broadcast_tcp(f"NEW_NODE {ip_novo}", excluir=ip_novo)
            print(f"[Cluster] Adicionado novo nó: {ip_novo}. Lista: {lista}")
        finally:
            ra_sair_rc()

    elif comando == "MACHINE_LIST" and len(partes) >= 2:
        lista = partes[1]
        try:
            ts_msg = int(partes[-1])
        except:
            ts_msg = incrementar_lamport_evento()
        atualizar_lamport_recebido(ts_msg)

        with trava:
            maquinas.clear()
            for ip in lista.split(","):
                ip = ip.strip()
                if ip:
                    maquinas.add(ip)
            maquinas.add(meu_ip)
        print(f"[Cluster] Lista de máquinas atualizada: {sorted(maquinas)}")

    elif comando == "NEW_NODE" and len(partes) >= 2:
        ip_novo = partes[1]
        try:
            ts_msg = int(partes[-1])
        except:
            ts_msg = incrementar_lamport_evento()
        atualizar_lamport_recebido(ts_msg)

        with trava:
            if ip_novo and ip_novo != meu_ip:
                maquinas.add(ip_novo)
        print(f"[Cluster] Novo nó divulgado: {ip_novo}. Lista: {sorted(maquinas)}")

# ================================
# Servidor TCP
# ================================
def tratar_cliente(conexao, endereco):
    try:
        dados = conexao.recv(4096).decode("utf-8").strip()
        if not dados:
            return

        partes = dados.split()
        if not partes:
            return

        if partes[0] == "TRANSFERENCIA":
            if len(partes) < 3:
                return
            try:
                valor = float(partes[1])
            except:
                conexao.sendall("ERRO: valor inválido".encode("utf-8"))
                return
            remetente = partes[2]
            if len(partes) >= 4:
                try:
                    atualizar_lamport_recebido(int(partes[3]))
                except:
                    incrementar_lamport_evento()
            else:
                incrementar_lamport_evento()

            if valor <= 0:
                conexao.sendall("ERRO: valor inválido".encode("utf-8"))
                return

            with trava:
                saldo_usuarios[usuario_logado] += valor
                transacoes_confirmadas.append(f"[{agora_legivel()}] + R${valor:.2f} recebido de {remetente}")
                print(f"[TRANSFERÊNCIA] Recebido R${valor:.2f} de {remetente}. Saldo atual: R${saldo_usuarios[usuario_logado]:.2f}")

            conexao.sendall(f"CONFIRMADO R${valor:.2f}".encode("utf-8"))
        else:
            processar_mensagem_controle(partes, endereco)

    except Exception as e:
        print(f"[ERRO] {e}")
    finally:
        try:
            conexao.close()
        except:
            pass

def iniciar_servidor():
    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    servidor.bind((HOST, PORTA_TCP))
    servidor.listen()
    print(f"[SERVIDOR TCP] Aguardando conexões em {HOST}:{PORTA_TCP}")
    while True:
        conexao, endereco = servidor.accept()
        threading.Thread(target=tratar_cliente, args=(conexao, endereco), daemon=True).start()

# ================================
# Fluxo de aplicação original
# ================================
def autenticar_usuario():
    global usuario_logado
    tentativas = 3
    while tentativas > 0:
        user = input("Usuário: ").strip()
        senha = input("Senha: ").strip()

        if user in usuarios_senhas and usuarios_senhas[user] == senha:
            with trava:
                if usuarios_logados.get(user, False):
                    print(f"Usuário {user} já está logado em outro equipamento!")
                    tentativas -= 1
                    continue
                else:
                    usuarios_logados[user] = True
                    if user not in saldo_usuarios:
                        saldo_usuarios[user] = 100.0
            usuario_logado = user
            print(f"Bem-vindo, {user}!")
            return True
        else:
            tentativas -= 1
            print(f"Usuário ou senha inválidos. Tentativas restantes: {tentativas}")

    print("Acesso negado! Encerrando o programa.")
    return False

def enviar_dinheiro(ip_destino, valor):
    global saldo_usuarios, usuario_logado
    if valor <= 0:
        print("Só é permitido enviar valores positivos maiores que zero!")
        return

    with trava:
        if saldo_usuarios[usuario_logado] < valor:
            print("Saldo insuficiente!")
            return
        saldo_usuarios[usuario_logado] -= valor
        transacoes_confirmadas.append(f"[{agora_legivel()}] - R${valor:.2f} enviado para {ip_destino}")
        print(f"[TRANSFERÊNCIA] Enviado R${valor:.2f} para {ip_destino}. Saldo atual: R${saldo_usuarios[usuario_logado]:.2f}")

    try:
        with socket.create_connection((ip_destino, PORTA_TCP), timeout=TIMEOUT_TCP) as cliente:
            ts = incrementar_lamport_evento()
            cliente.sendall(f"TRANSFERENCIA {valor} {usuario_logado} {ts}".encode("utf-8"))
            cliente.settimeout(TIMEOUT_TCP)
            resposta = cliente.recv(1024).decode("utf-8")
            print(f"[DESTINO] {resposta}")
    except Exception as e:
        print(f"[ERRO NA TRANSFERÊNCIA] {e}")

def conectar_maquina(ip_alvo):
    if ip_alvo == meu_ip:
        print("[Cluster] Ignorando pedido para si mesmo.")
        return
    with trava:
        maquinas.clear()
        maquinas.add(meu_ip)

    print(f"[Cluster] Solicitando conexão ao nó {ip_alvo}...")
    enviar_mensagem_tcp(ip_alvo, f"JOIN_REQUEST {meu_ip}")

def interface_usuario():
    global saldo_usuarios, usuario_logado
    while True:
        msg = input()
        if msg.startswith("\\enviar"):
            try:
                partes = msg.split()
                ip_destino = partes[1]
                valor = float(partes[2])
                enviar_dinheiro(ip_destino, valor)
            except:
                print("Uso correto: \\enviar <ip_destino> <valor>")

        elif msg == "\\saldo":
            with trava:
                print(f"[SALDO] Saldo atual: R${saldo_usuarios[usuario_logado]:.2f}")

        elif msg == "\\historico":
            with trava:
                print("=== Histórico de transações ===")
                for t in transacoes_confirmadas:
                    print(t)

        elif msg == "\\maquinas":
            with trava:
                print(f"=== Máquinas no cluster (coord = primeiro) ===")
                for ip in sorted(maquinas):
                    marca = " (COORD)" if ip == (sorted(maquinas)[0] if maquinas else "") else ""
                    print(f"{ip}{marca}")

        elif msg.startswith("\\conectar"):
            try:
                _, ip_alvo = msg.split()
                conectar_maquina(ip_alvo)
            except:
                print("Uso correto: \\conectar <ip_maquina>")

        elif msg == "\\sync":
            disparar_berkeley()

        elif msg == "\\sair":
            with trava:
                usuarios_logados[usuario_logado] = False
            print("Encerrando sistema...")
            break

        else:
            print("[COMANDO INVÁLIDO] Use \\enviar, \\saldo, \\historico, \\maquinas, \\conectar <ip>, \\sync ou \\sair.")

# ================================
# Inicialização
# ================================
if __name__ == "__main__":
    meu_ip = obter_ip_local()
    with trava:
        maquinas.add(meu_ip)

    threading.Thread(target=iniciar_servidor, daemon=True).start()
    threading.Thread(target=listener_udp, daemon=True).start()

    if autenticar_usuario():
        print("=== SISTEMA DE TRANSFERÊNCIAS (Distribuído) ===")
        print("============= MENU ==============")
        print("\\enviar <ip_destino> <valor> ..... Enviar dinheiro (TCP)")
        print("\\saldo ........................... Ver saldo atual")
        print("\\historico ....................... Ver histórico")
        print("\\maquinas ........................ Ver máquinas do cluster")
        print("\\conectar <ip> ................... Conectar-se a um cluster remoto (JOIN)")
        print("\\sync ............................ Sincronizar relógios (Berkeley/UDP)")
        print("\\sair ............................ Encerrar sistema")

        interface_usuario()
