from agno.tools import Toolkit

class MilhasCalculator(Toolkit):
    def __init__(self):
        super().__init__(name="calculadora_milhas")
        self.register(self.calculate_cpm)
        self.register(self.calculate_bonus_miles)
        self.register(self.calculate_mixed_transfer)

    def calculate_cpm(self, custo_total: float, milhas_totais: int) -> float:
        """
        Calcula o CPM (Custo Por Milheiro) Real.
        Fórmula: (custo / milhas) * 1000
        """
        if milhas_totais == 0: return 0.0
        return round((custo_total / milhas_totais) * 1000, 2)

    def calculate_bonus_miles(self, milhas_base: int, bonus_percent: float) -> int:
        """
        Calcula o total de milhas creditadas após o bônus.
        Ex: 1000 milhas + 100% bonus = 2000 milhas.
        """
        return int(milhas_base * (1 + bonus_percent / 100))

    def calculate_mixed_transfer(self, 
                               lote_organico_milhas: int, 
                               lote_organico_cpm: float,
                               lote_pago_milhas: int,
                               preco_milheiro_pago: float,
                               bonus_percent: float) -> str:
        """
        Calcula o CPM Final de uma transferência que mistura milhas orgânicas (antigas)
        com milhas compradas (novas), aplicando o bônus no total.
        Retorna uma string explicativa com o cálculo detalhado.
        """
        # 1. Custos
        custo_organico = (lote_organico_milhas / 1000) * lote_organico_cpm
        custo_pago = (lote_pago_milhas / 1000) * preco_milheiro_pago
        custo_total = custo_organico + custo_pago

        # 2. Milhas
        total_transferido = lote_organico_milhas + lote_pago_milhas
        total_creditado = int(total_transferido * (1 + bonus_percent / 100))

        # 3. CPM Final
        cpm_final = 0.0
        if total_creditado > 0:
            cpm_final = (custo_total / total_creditado) * 1000

        return (f"--- Resultado do Cálculo Misto ---\n"
                f"1. Total Transferido: {total_transferido:,} milhas\n"
                f"2. Total Creditado (com {bonus_percent}% bônus): {total_creditado:,} milhas\n"
                f"3. Custo Total: R$ {custo_total:.2f}\n"
                f"4. CPM FINAL: R$ {cpm_final:.2f}")
