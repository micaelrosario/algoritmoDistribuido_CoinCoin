import socket, threading, time, random


# Variáveis globais
saldo = 0
PORTA_DESCOBERTA = 12000

# Obtém o IP local da máquina
def findIP():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    ip = s.getsockname()[0]
    s.close()
    return ip


#Meu endereço IP
meu_ip = findIP()
print(f"IP local: {meu_ip}")

transacoes_pendentes = {}  # Transações aguardando confirmação
transacoes_confirmadas = []  # Histórico de transações
usuarios = {
    "aluno": {
        'usuario': "aluno",
        'senha': "123",
        'saldo': 100.0,
        'ip': meu_ip,
        'porta': random.randint(10000, 60000)
    },
    "professor": {
        'usuario': "professor",
        'senha': "123",
        'saldo': 500.0,
        'ip': meu_ip,
        'porta': random.randint(10000, 60000)
    }
}  # Dicionário para armazenar usuários e senhas


# Configuração de sockets
socket_local = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
porta_local = random.randint(10000, 60000)  # Porta única para este usuário
socket_local.bind((meu_ip, porta_local))
socket_local.listen(5)

# Crie um novo socket para a porta fixa de descoberta
socket_descoberta = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
socket_descoberta.bind((meu_ip, PORTA_DESCOBERTA))
socket_descoberta.listen(5)

# Semáforos para controle de concorrência
semaforo_usuarios = threading.BoundedSemaphore(1)
semaforo_transacoes = threading.BoundedSemaphore(1)
semaforo_saldo = threading.BoundedSemaphore(1)


# Listas para controle distribuído
hosts = set() 
concordou = set()  
neguei = set()  
critica = False  
relogio_critica = 0  
mensagem_critica = "" 
ajuste = 0  



def sendto(mensagem, usuario_destino):
    """Envia mensagem para outro usuário com timestamp"""
    relogio = time.time() + ajuste
    msg = f"{mensagem} {relogio}"
   
    ip = usuarios[usuario_destino]['ip']
    porta = usuarios[usuario_destino]['porta']
    
    if ip != meu_ip:
        try:
            socket_temp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            socket_temp.connect((ip, porta))
            socket_temp.send(msg.encode())
            socket_temp.close()
        except:
            print(f"Erro ao enviar para {usuario_destino} ({ip}:{porta})")


def solicita_regiao_critica(mensagem):
    """Solicita acesso à região crítica para realizar transação"""
    global relogio_critica, mensagem_critica
    mensagem_critica = mensagem
    relogio_critica = time.time() + ajuste
   
    print("Solicitando acesso à região crítica...")
    if len(hosts) >= 1:
        for ip in hosts:
            sendto("\\request", ip)
    else:
        pass
    # se só tiver ele não precisar enviar request, apenas dar acesso a região critica      


def liberar_regiao_critica():
    """Libera a região crítica após transação"""
    global neguei, critica
    print("Liberando região crítica...")
   
    for ip in neguei:
        sendto("\\accept", ip)
    neguei.clear()
    critica = False


def processar_transacao(mensagem, origem):
    """Processa uma transação financeira"""
    global saldo, transacoes_pendentes, transacoes_confirmadas
   
    partes = mensagem.split()
    if len(partes) < 4:
        return "Formato inválido"
   
    tipo = partes[1]
    destinatario = partes[2]
   
    try:
        valor = float(partes[3])
    except ValueError:
        return "Valor inválido"
   
    if tipo == "emprestar":
        # OPERAÇÃO FINANCEIRA: Empréstimo
        semaforo_saldo.acquire()
        semaforo_transacoes.acquire()
       
        # Registrar transação pendente
        id_transacao = f"{origem}_{destinatario}_{time.time()}"
        transacoes_pendentes[id_transacao] = {
            'de': origem,
            'para': destinatario,
            'valor': valor,
            'status': 'pendente'
        }
       
        semaforo_transacoes.release()
        semaforo_saldo.release()
       
        return f"Transação de empréstimo registrada. Aguardando confirmação de {destinatario}"
   
    elif tipo == "confirmar":
        # OPERAÇÃO FINANCEIRA: Confirmação de transação
        semaforo_saldo.acquire()
        semaforo_transacoes.acquire()
       
        # Buscar transação pendente
        transacao_encontrada = None
        for id_transacao, transacao in transacoes_pendentes.items():
            if (transacao['para'] == origem and
                transacao['de'] == destinatario and
                transacao['status'] == 'pendente'):
                transacao_encontrada = transacao
                transacao_id = id_transacao
                break
       
        if transacao_encontrada:
            # Atualizar saldos
            if origem in usuarios:
                usuarios[origem]['saldo'] -= transacao_encontrada['valor']
            if destinatario in usuarios:
                usuarios[destinatario]['saldo'] += transacao_encontrada['valor']
           
            # Registrar transação confirmada
            transacoes_confirmadas.append({
                'de': transacao_encontrada['de'],
                'para': transacao_encontrada['para'],
                'valor': transacao_encontrada['valor'],
                'timestamp': time.strftime("%Y-%m-%d %H:%M:%S")
            })
           
            # Remover transação pendente
            del transacoes_pendentes[transacao_id]
           
            semaforo_transacoes.release()
            semaforo_saldo.release()
           
            return f"Transação confirmada! Saldo atualizado."
        else:
            semaforo_transacoes.release()
            semaforo_saldo.release()
            return "Transação não encontrada"
   
    return "Operação desconhecida"


#colocar enviar e receber junto
def receber():
    """Thread para receber mensagens de outros usuários"""
    global socket_local, hosts, ajuste
    global critica, relogio_critica, mensagem_critica, concordou
   
    while True:
        connection, address = socket_local.accept()
        mensagem_completa = connection.recv(256).decode()
        connection.close()
       
        if not mensagem_completa:
            continue
       
        # Separar mensagem e timestamp
        partes = mensagem_completa.rsplit(' ', 1)
        if len(partes) < 2:
            continue
           
        mensagem = partes[0]
        relogio_recebido = float(partes[1])
       
        # Sincronização de relógio lógico (Lamport)
        relogio_logico = time.time() + ajuste
        if relogio_recebido > relogio_logico:
            ajuste = relogio_recebido - time.time() + 1

        print("Chegou na função de receber")

        # Processar mensagens do sistema
        if mensagem.startswith("\\connect"):
            confirmarcao = input("Deseja confirmar conexão? SIM/NÃO\n:").upper()
            if confirmarcao == "SIM":
                sendto("\\ok", address[0])
                print("Conexão confirmada")

                semaforo_usuarios.acquire()
                hosts.add(address[0])
                semaforo_usuarios.release()

                for ip in hosts:
                    if ip != address[0]:
                        sendto(f"\\host {ip}", address[0])
                        sendto(f"\\Usuário: [{address[0]}] está conectado a rede", ip)

                print("Acessando o Sistema Financeiro...")
                time.sleep(3)
                menu_login()
            else:
                print("Negando Conexão...")
                sendto(f"Solicitação de conexão negada pelo IP {meu_ip}", address[0])
           
        elif mensagem.startswith("\\ok"):
            semaforo_usuarios.acquire()
            hosts.add(address[0])
            semaforo_usuarios.release()
           
        elif mensagem.startswith("\\request"):
           
            # Não estou usando a região crítica nem tenho interesse
            if not critica and relogio_critica == 0:
                sendto("\\accept", address[0])
            # Não estou usando a região crítica, mas quero usar e pedi depois
            elif not critica and relogio_critica > 0 and relogio_critica > relogio_recebido:
                sendto("\\accept", address[0])
            else:
                neguei.add(address[0])
               
        elif mensagem.startswith("\\accept"):
            print(f"{address[0]} concordou com a transação")
            concordou.add(address[0])
           
            # Verificar se todos concordaram
            if len(hosts - concordou) == 1:
                critica = True
                concordou.clear()
               
                # Processar a transação na região crítica
                resultado = processar_transacao(mensagem_critica, meu_ip)
                print(resultado)
               
                liberar_regiao_critica()
                print("Região crítica liberada!")
       
        # Processar mensagens de transação
        elif mensagem.startswith("\\transacao"):
            resposta = processar_transacao(mensagem, address[0])
            sendto(f"\\resposta {resposta}", address[0])

        elif mensagem.startswith("\\negado"):
            print("Encerrando sistema...")
            return False
        else:
            print(f"Mensagem desconhecida recebida de {address[0]}: {mensagem}")

def send_initial_connect(ip_destino, porta_destino, meu_usuario):
    """Envia a mensagem inicial de conexão para um IP e porta específicos."""
    try:
        mensagem = f"\\connect {meu_usuario} {porta_local}"
        socket_temp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        socket_temp.connect((ip_destino, porta_destino))
        socket_temp.send(mensagem.encode())
        socket_temp.close()
        print(f"Tentando se conectar a {ip_destino}:{porta_destino}...")
        return True
    except Exception as e:
        print(f"❌ Falha ao conectar em {ip_destino}:{porta_destino}. Erro: {e}")
        return False

def conectar_por_ip(ip_destino):
    """Conecta com outro usuário pelo nome"""
    if ip_destino not in usuarios:
        print(f"Usuário {ip_destino} não encontrado no sistema.")
        return False

    try:
        sendto("\\connect", ip_destino)
        send_initial_connect("\\connect", porta_local)
        print(f"Tentando se conectar ao usuário: {ip_destino} ({usuarios[ip_destino]['ip']}:{usuarios[ip_destino]['porta']})")
        return True
    except:
        print(f"Erro ao conectar com {ip_destino}")
        return False

def iniciar_conexao():
    global hosts

    print("=== INICIANDO A CONEXÃO ===\n")
    ip = input("Digite o endereço IP para se conectar (ou pressione ENTER para iniciar como coordenador): ").strip()

    if ip == "":
        print("Nenhum IP informado. Iniciando como COORDENADOR...")
        return menu_login()
    else:
        try:
            conectar_por_ip(ip)
            print(f"Tentando se conectar a {ip}...")
            return True
        except Exception as e:
            print(f"❌ Falha ao conectar em {ip}. Iniciando como COORDENADOR.")
            return menu_login()


def enviar_mensagem():
    """Thread para enviar mensagens, com menu de opções e listagem de usuários."""
    global meu_usuario_logado

    while True:
        print("\n" + "="*60)
        print("Opções de Operação:")
        print("1. Solicitar Empréstimo")
        print("2. Confirmar Transação")
        print("3. Consultar Saldo")
        print("4. Ver Histórico de Transações")
        print("6. Conectar a Outro Usuário") # Nova opção!
        print("7. Sair")
        print("="*60)
        
        opcao = input("\nEscolha uma opção (1-7): ")
        
        if opcao == "1":
            # Operação de Empréstimo
            print("\n=== USUÁRIOS CONECTADOS ===")
            # Lista todos os usuários, exceto o próprio
            usuarios_conectados = [user for user in usuarios if user != meu_usuario_logado]
            
            if not usuarios_conectados:
                print("⚠️ Não há outros usuários conectados. Você precisa se conectar a alguém primeiro.")
                continue
                
            for user in usuarios_conectados:
                print(f"- {user}")
                
            destinatario = input("Para qual usuário deseja emprestar? ")
            
            if destinatario not in usuarios:
                print(f"❌ Usuário '{destinatario}' não encontrado. Verifique a lista e tente novamente.")
                continue
            
            valor = input("Qual o valor do empréstimo? ")
            
            try:
                valor_float = float(valor)
                mensagem = f"\\emprestar {destinatario} {valor_float}"
                solicita_regiao_critica(mensagem)
                print(f"Solicitando empréstimo para {destinatario} no valor de R$ {valor_float:.2f}")
            except ValueError:
                print("❌ Valor inválido. Tente novamente.")
                
        elif opcao == "2":
            # Operação de Confirmação
            print("\n=== USUÁRIOS CONECTADOS ===")
            usuarios_conectados = [user for user in usuarios if user != meu_usuario_logado]
            
            if not usuarios_conectados:
                print("⚠️ Não há outros usuários conectados.")
                continue
            
            for user in usuarios_conectados:
                print(f"- {user}")

            origem = input("De qual usuário deseja confirmar a transação? ")

            if origem not in usuarios:
                print(f"❌ Usuário '{origem}' não encontrado. Verifique a lista e tente novamente.")
                continue

            mensagem = f"\\confirmar {origem}"
            solicita_regiao_critica(mensagem)
            print(f"Confirmando transação de {origem}")

        elif opcao == "3":
            # Consultar Saldo
            semaforo_saldo.acquire()
            if meu_usuario_logado in usuarios:
                print(f"Seu saldo atual é: R$ {usuarios[meu_usuario_logado]['saldo']:.2f}")
            else:
                print("Usuário não encontrado. Ocorreu um erro.")
            semaforo_saldo.release()

        elif opcao == "4":
            # Mostrar Transações
            print("\n=== TRANSAÇÕES CONFIRMADAS ===")
            for transacao in transacoes_confirmadas:
                print(f"{transacao['timestamp']}: {transacao['de']} -> {transacao['para']} R$ {transacao['valor']:.2f}")
                
            print("\n=== TRANSAÇÕES PENDENTES ===")
            for id_transacao, transacao in transacoes_pendentes.items():
                print(f"Pendente: {transacao['de']} -> {transacao['para']} R$ {transacao['valor']:.2f}")

        elif opcao == "5":
            # Sair
            print("Encerrando sistema...")
            break
            
        else:
            print("Opção inválida. Tente novamente.")


def menu_login():
    """Menu de login/cadastro de usuários"""
    global usuarios, meu_ip, porta_local, meu_usuario_logado # Adicionando 'meu_usuario_logado'

    while True:
        print("\n" + "="*60)
        print("======= BEM VINDO AO COINCOIN - SISTEMA FINANCEIRO =======")
        print("="*60)

        print("\n1 - Criar novo usuário")
        print("2 - Fazer login")
        print("3 - Sair")

        opcao = input("\nEscolha uma opção: ")

        if opcao == "1":
            usuario = input('Digite um nome de usuário: ')
            senha = input('Digite a senha: ')

            semaforo_usuarios.acquire()
            if usuario in usuarios:
                print("⚠️ Usuário já existe, escolha outro nome.")
            else:
                usuarios[usuario] = {
                    'usuario': usuario,
                    'senha': senha,
                    'saldo': 0.0,
                    'ip': meu_ip,
                    'porta': porta_local # Use a porta local do socket
                }
                print(f"Usuário '{usuario}' cadastrado com sucesso! Porta: {usuarios[usuario]['porta']}")
            semaforo_usuarios.release()

        elif opcao == "2":
            usuario = input('Digite o seu usuário: ')
            senha = input('Digite a sua senha: ')

            semaforo_usuarios.acquire()
            if usuario in usuarios and usuarios[usuario]['senha'] == senha:
                # Armazenar o usuário logado globalmente para uso nas funções de rede
                meu_usuario_logado = usuario
                
                # Atualizar a porta do usuário no dicionário para a porta local do socket
                usuarios[usuario]['porta'] = porta_local
                
                print(f"✅ Login realizado com sucesso! Bem-vindo {meu_usuario_logado}")
                print(f"Seu IP: {usuarios[meu_usuario_logado]['ip']} | Porta: {usuarios[meu_usuario_logado]['porta']}")
                semaforo_usuarios.release()
                return True
            else:
                print("❌ Usuário ou senha incorretos!")
                semaforo_usuarios.release()

        elif opcao == "3":
            print("Encerrando sistema...")
            return False
        else:
            print("Opção inválida!")


# Inicialização do sistema
if __name__ == "__main__":
    if iniciar_conexao():
        # Iniciar threads
        t_receber = threading.Thread(target=receber, daemon=True)
        t_enviar = threading.Thread(target=enviar_mensagem)
        t_receber.start()
        t_enviar.start()
    
        t_enviar.join()