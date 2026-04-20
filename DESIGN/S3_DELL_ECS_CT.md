# Configuration S3 Dell ECS Cloud Temple

## ✅ Configuration Finale Validée - HYBRIDE SigV2/SigV4


### Configuration boto3 HYBRIDE (SOLUTION OPTIMALE)
```python
# Client SigV2 pour opérations sur données (PUT/GET/DELETE)
config_v2 = Config(
    region_name='fr1',
    signature_version='s3',  # SigV2 legacy
    s3={'addressing_style': 'path'},
    retries={'max_attempts': 3, 'mode': 'adaptive'}
)

client_v2 = boto3.client('s3', endpoint_url=..., config=config_v2)

# Client SigV4 pour opérations métadonnées (HEAD/LIST)
config_v4 = Config(
    region_name='fr1',
    signature_version='s3v4',
    s3={'addressing_style': 'path', 'payload_signing_enabled': False},
    retries={'max_attempts': 3, 'mode': 'adaptive'}
)

client_v4 = boto3.client('s3', endpoint_url=..., config=config_v4)
```

## 🎯 Tests Validés (27/01/2026) - 5/5 RÉUSSIS ✅

### Configuration HYBRIDE - TOUS LES TESTS PASSENT
- **HEAD BUCKET** (SigV4): ✅ SUCCESS
- **LIST_OBJECTS_V2** (SigV4): ✅ SUCCESS
- **PUT OBJECT** (SigV2): ✅ SUCCESS
- **GET OBJECT** (SigV2): ✅ SUCCESS
- **DELETE OBJECT** (SigV2): ✅ SUCCESS

## 📝 Historique du Debug

### Problème initial
- **SigV4** génère systématiquement `XAmzContentSHA256Mismatch`
- Tous les tests PUT échouaient
- MC (MinIO Client) fonctionne, boto3 échoue

### Solution trouvée
- **Passer en SigV2** (signature legacy)
- Dell ECS (ViPR/1.0) supporte mieux SigV2 que SigV4 pour les opérations de données


## 📚 Références
- Dell ECS Documentation: Supporte SigV2 et SigV4
- Cloud Temple: Endpoint régional fr1
- Boto3: `signature_version='s3'` pour SigV2
 