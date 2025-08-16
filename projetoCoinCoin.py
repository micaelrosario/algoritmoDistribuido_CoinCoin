import socket, threading, time


saldo = 0
socket_local = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
socket_udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
porta_local = 12000
porta_udp = 13000


def findIP ():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    ip = s.getsockname()[0]
    s.close()
    return ip
meu_ip = findIP()
print (meu_ip)




socket_udp.bind((meu_ip, porta_udp))
socket_local.bind((meu_ip, porta_local))
socket_local.listen()


semaforo_hosts = threading.BoundedSemaphore(1)
semaforo_mensagens = threading.BoundedSemaphore(1)


#Listas
lista_usuarios = {} # usuário e Senha
concordou = []
neguei = []
critica = False
relogio_critica = 0
mensagem_critica = ""




mensagens = []
lista_diferencas = []




def print_mensagens():
    global ip, mensagens
#   os.system('cls')
    if len(mensagens) > 10:
        msgs = mensagens[-10:]
    else:
        msgs = mensagens
   
    for item in msgs:
        if (item[1] == meu_ip):
            pronome = "You"
        else:
            pronome = ".".join(item[1].split(".")[2:])
        while (len(pronome) < 7):
            pronome += " "
        print (pronome+": "+item[0])
   
def sendto(mensagem, ip):
    relogio = time.time() + ajuste
    msg = mensagem + " " + str(relogio)
    socket_temp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    socket_temp.connect(ip)
    socket_temp.send(msg.encode())
    socket_temp.close()


def solicita_regiao (mensagem):
   
    global relogio_critica, lista_usuarios, ajuste, mensagem_critica
    mensagem_critica = mensagem
    print ("solicitei")
    relogio_critica = time.time() + ajuste
    for ip in lista_usuarios:
        sendto("\\request",ip)


def liberar_regiao ():
    global relogio_critica, neguei, critica
    print ("liberei")
    for ip in neguei:
        sendto("\\accept",(ip,12000))
    neguei.clear()


def receber ():
    global socket_local, socket_udp, semaforo_hosts, lista_usuarios, mensagens, ajuste, critica, relogio_critica, mensagem_critica, concordou
    while True:
        connection, address = socket_local.accept()
        mensagem = connection.recv(256).decode()




        #Relógio de Lamport
        relogio_recebido = float(mensagem.split(" ")[-1])
        relogio_logico = time.time() + ajuste
        if relogio_recebido > relogio_logico:
            ajuste  = relogio_recebido - time.time() + 1
        connection.close()
       
        # Implementação do Berkley
        lista_diferencas.append((relogio_recebido, address))
        if lista_diferencas.length() == lista_usuarios.length:
            #calcula média
            soma = 0
            for item in lista_diferencas:
                soma+=item[0]
                media = soma / (lista_diferencas.length() + 1)
                #ajusta relogio do coordenador
                ajuste += media
                for item in lista_diferencas:
                    ajuste_resposta = media+item[0]
                    semaforo_hosts.acquire()
                    socket_udp.sendto(str(ajuste_resposta).encode(), item[1])
                    semaforo_hosts.release()
                   
       
        if mensagem[:8]=="\\connect":
            sendto("\\ok",(address[0],12000))
            for ip in lista_usuarios:
                sendto("\\host "+ip,(address[0],12000))
            semaforo_hosts.acquire()
            lista_usuarios.add((address[0],12000))
            semaforo_hosts.release()
        elif mensagem[:3]=="\\ok":
            semaforo_hosts.acquire()
            lista_usuarios.add((address[0],12000))
            semaforo_hosts.release()
        elif mensagem[:8]=="\\request":
            print ("recebi requisicao")
            #não estou usando a regiao critica nem tenho interesse
            if critica == False and relogio_critica == 0:
                sendto("\\accept",(address[0],12000))
            #não estou usando a regiao critica, mas quero usar regiao e pedi depois
            elif critica == False and relogio_critica > 0 and relogio_critica > relogio_recebido:
                sendto("\\accept",(address[0],12000))
        elif mensagem[:7]=="\\accept":
            print (address[0]+" concordou")




            #adicionar o host que concordou com a requesição
            concordou.add((address[0],12000))
            #verificar se todos concordaram com meu uso da regiao critica
            if concordou == lista_usuarios:
                critica = True
                concordou.clear()
                escrever_mensagem(mensagem_critica,(meu_ip,12000))
                liberar_regiao()
                print("Região crítica Liberada!")
        else:
            escrever_mensagem(mensagem,address)
               
def escrever_mensagem (mensagem,address):
    semaforo_mensagens.acquire()
    mensagens.append((mensagem,address[0]))
    semaforo_mensagens.release()
    print_mensagens()
    print ("Mensagem Escrita: ")


def acesso():
    while True:
        print("=" * 80)
        print("            BEM VINDO AO GERENCIADOR DE OPERAÇÕES FINANCEIRAS ")
        print("=" * 80)
        opcao = input("Deseja criar um novo usuário ou Logar? \n 1- Criar novo usuário \n 2- Fazer login \n 3- Sair\n\nEscolha: ")
        
        if opcao == "1":
            usuario = input('Digite um nome de usuário: ')
            senha = input('Digite a senha: ')
            
            # Verificação simples para evitar que o usuário seja substituído
            if usuario in lista_usuarios:
                print(f"O usuário '{usuario}' já existe. Por favor, escolha outro nome.")
            else:
                lista_usuarios[usuario] = senha
                print('Usuário Cadastrado com sucesso!')
        
        elif opcao == "2":
            usuario = input('Digite o seu usuário: ')
            senha = input('Digite a sua senha: ')
            
            # Lógica de verificação correta:
            # 1. Verifica se o usuário existe no dicionário
            if usuario in lista_usuarios:
                # 2. Se existe, verifica se a senha fornecida corresponde à senha armazenada
                if lista_usuarios[usuario] == senha:
                    print("Usuário Logado com sucesso!")
                    # Aqui você pode chamar a função principal do seu programa
                    # para continuar as operações financeiras.
                    return True # Retorna True para indicar login bem-sucedido
                else:
                    print("Senha incorreta!")
            else:
                print("Usuário não encontrado!")
        
        elif opcao == "3":
            print("Encerrando sistema...")
            break  # Interrompe o loop e encerra a função
            
        else:
            print("Opção inválida! Por favor, escolha 1, 2 ou 3.")


def enviar ():
    global socket_local, mensagens, semaforo_mensagens
    acesso()

t1 = threading.Thread(target=receber)
t2 = threading.Thread(target=enviar)

t1.start()
t2.start()