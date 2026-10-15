"""MNI requires per-court homologation; never return simulated official results."""
from django.core.exceptions import PermissionDenied

class MNIServiceError(Exception):
    pass

class MNIService:
    def __init__(self, deployment):
        self.deployment = deployment

    def consultar_avisos_pendentes(self, id_consultante):
        raise MNIServiceError("Consulta MNI ainda não homologada para este tribunal.")

    def consultar_teor_comunicacao(self, id_comunicacao):
        raise MNIServiceError("Leitura MNI ainda não homologada para este tribunal.")

    def entregar_manifestacao(self, actor, case_number, doc_payload, grant_id=None):
        raise PermissionDenied("Peticionamento judicial direto não está habilitado.")
