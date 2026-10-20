"""Validación del modelo CAMS contra mediciones: cifras que se publican junto a la estimación."""
import unittest

from aeris_web.modelo import lista, validar


class ValidacionModeloTests(unittest.TestCase):
    def test_sesgo_categorias_y_dias_no_buenos(self):
        # (medido, modelo): el modelo subestima y no detecta un día Aceptable.
        pares = [(10, 8), (20, 14), (30, 26), (12, 10)]
        v = validar(pares)
        self.assertEqual(v['dias'], 4)
        self.assertAlmostEqual(v['sesgo'], -3.5)
        # Categorías medido/modelo: Buena/Buena, Aceptable/Buena, Mala/Mala, Buena/Buena.
        self.assertEqual(v['misma_categoria'], 75)
        self.assertEqual((v['no_buenos'], v['no_buenos_detectados']), (2, 50))
        self.assertGreater(v['r'], .9)

    def test_sin_dias_no_buenos_no_inventa_porcentaje(self):
        self.assertIsNone(validar([(5, 6), (8, 7)])['no_buenos_detectados'])

    def test_lista_de_estaciones(self):
        self.assertEqual(lista(['A']), 'A')
        self.assertEqual(lista(['A', 'B', 'C']), 'A, B y C')


if __name__ == '__main__':
    unittest.main()
