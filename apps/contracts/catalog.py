"""The builder accepts only these literal placeholders, never template code."""

VARIABLES = {
    "escritorio_nome": ("Nome / razão social do escritório", "Escritório"),
    "escritorio_documento": ("CPF / CNPJ do escritório", "Escritório"),
    "escritorio_endereco": ("Endereço do escritório", "Escritório"),
    "advogado_nome": ("Advogado responsável", "Escritório"),
    "advogado_oab": ("Inscrição na OAB", "Escritório"),
    "cliente_nome": ("Nome / razão social do contratante", "Contratante"),
    "cliente_documento": ("CPF / CNPJ do contratante", "Contratante"),
    "cliente_endereco": ("Endereço do contratante", "Contratante"),
    "cliente_email": ("E-mail do contratante", "Contratante"),
    "cliente_telefone": ("Telefone do contratante", "Contratante"),
    "pasta_titulo": ("Título da pasta", "Objeto e condições"),
    "objeto": ("Objeto e limites dos serviços", "Objeto e condições"),
    "honorarios": ("Honorários e condições de pagamento", "Objeto e condições"),
    "vigencia": ("Vigência / conclusão", "Objeto e condições"),
    "condicoes": ("Outras condições acordadas", "Objeto e condições"),
    "cidade": ("Cidade", "Formalização"),
    "data": ("Data do instrumento", "Formalização"),
}

MULTILINE = {"objeto", "honorarios", "vigencia", "condicoes", "escritorio_endereco", "cliente_endereco"}

EXAMPLE_TITLE = "Prestação de serviços jurídicos — base editável"
EXAMPLE_BODY = """INSTRUMENTO DE PRESTAÇÃO DE SERVIÇOS JURÍDICOS

CONTRATANTE: [[cliente_nome]], CPF/CNPJ [[cliente_documento]], com endereço em [[cliente_endereco]].

CONTRATADO: [[escritorio_nome]], CPF/CNPJ [[escritorio_documento]], com endereço em [[escritorio_endereco]], representado por [[advogado_nome]], OAB [[advogado_oab]].

1. OBJETO E ESCOPO
[[objeto]]
Referência interna: [[pasta_titulo]].

2. HONORÁRIOS E PAGAMENTO
[[honorarios]]

3. VIGÊNCIA
[[vigencia]]

4. CONDIÇÕES COMPLEMENTARES
[[condicoes]]

[[cidade]], [[data]].

________________________________
[[cliente_nome]] — Contratante

________________________________
[[advogado_nome]] — Contratado
"""
