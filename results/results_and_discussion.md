# IV. RESULTS AND DISCUSSION

Dataset composition target: 4 natural images, 4 textured images, 4 smooth images, 4 high-edge images, and 4 low-edge images.

## A. System Performance Across Different Image Resolutions

### Table 2. Image Resolution vs Available Edge Pixels and Embedding Capacity

| Image Resolution | Available Edge Pixels (avg) | Embedding Capacity (byte avg) |
|---|---:|---:|
| 128x128 | 853.99 | 202.67 |
| 256x256 | 5423.33 | 723.33 |
| 512x512 | N/A | N/A |
| 1024x1024 | N/A | N/A |

### Table 2.1 Image Resolution vs Embedding/Extraction Time and Extraction Accuracy

| Image Resolution | Embedding Time (ms) | Extraction Time (ms) | Extraction Accuracy |
|---|---:|---:|---:|
| 128x128 | 23.2726 | 30.5695 | 100.00% |
| 256x256 | 92.3412 | 80.1701 | 100.00% |
| 512x512 | N/A | N/A | N/A |
| 1024x1024 | N/A | N/A | N/A |

Screenshots of 20 embedding and extraction results:
- Screenshot 1: results/study20_128_820d5a3fb9694622a534de68fcc197bb.png
- Screenshot 2: results/study20_128_117caf68f0a4419faa1ca1db8f5276ce.png
- Screenshot 3: results/study20_128_f1a95d44d68d4e28b310185b9e22ceb5.png
- Screenshot 4: results/study20_128_f1633443bf884cf9bc929ac1b62b6786.png
- Screenshot 5: results/study20_128_f90e0a1913e34bf9aad484efd3add074.png
- Screenshot 6: results/study20_128_f32c55dfc7c9498c92ac442b5c033a92.png
- Screenshot 7: results/study20_128_7a858d8546614fe78c3f67921a666f87.png
- Screenshot 8: results/study20_128_5de0481ae11d42e7823f424898026ae8.png
- Screenshot 9: results/study20_128_aded07443876490a9e8e8241e828ea1b.png
- Screenshot 10: results/study20_128_fe67ff3698584a9281d18742b1da4753.png
- Screenshot 11: results/study20_128_c5d96d9431cf4a0b90efd0d0f8cae8b3.png
- Screenshot 12: results/study20_128_62564c92ef374efe9ae4db42fd0d78fa.png
- Screenshot 13: results/study20_128_2ffc550b640049e28a770aebae7553d4.png
- Screenshot 14: results/study20_128_cebd82fe6dfd4cf18d5f2eaed2cd17e2.png
- Screenshot 15: results/study20_128_29c2956179204304bdcbc55642ae9b4f.png
- Screenshot 16: results/study20_128_f4002564b1e8495bae6fe78d4ee45d17.png
- Screenshot 17: results/study20_128_3141be2bd0034bf094d92e80e31e6ac2.png
- Screenshot 18: results/study20_128_3d7f9059f6df483e965c5a950e79f023.png
- Screenshot 19: results/study20_128_dfac07481c1440358be4eb8eaf0e4ddf.png
- Screenshot 20: results/study20_128_9b51850f5a464f0dbccbae1033c82c54.png

20 recovered secret messages (proof that extraction matches original):
- Run 1: Message extracted successfully with 100% accuracy. Extracted: qwertyuiopasdfghjklazxcvbnm
- Run 2: Message extracted successfully with 100% accuracy. Extracted: ahdbf adbgadhn abgdfhan qwertyuiopasdfghjklzxcvbnmqwertyuiopasdfghjklzxcvbnmqwertyuiopasdfghjklzxcvbnmqwertyuiopasdfghjklzxcvbnmqwertyuiopasdfghjklzxcvbnm
- Run 3: Message extracted successfully with 100% accuracy. Extracted: qwertyuiopasdfghjklzxcvbnm
- Run 4: Message extracted successfully with 100% accuracy. Extracted: qwertyuiopasdfghjklzxcvbnmqwertyuiopasdfghjklzxcvbnmqwertyuiopasdfghjklzxcvbnmqwertyuiopasdfghjklzxcvbnmqwertyuiopasdfghjklzxcvbnm
- Run 5: Message extracted successfully with 100% accuracy. Extracted: qwertyuiopasdfghjklzxcvbnmqwertyuiopasdfghjklzxcvbnmqwertyuiopasdfghjklzxcvbnmqwertyuiopasdfghjklzxcvbnmqwertyuiop
- Run 6: Message extracted successfully with 100% accuracy. Extracted: qwertyuiopasdfghjklzxcvbnmqwertyuiopasdfghjklzxcvbnmqwertyuiopasdfghjklzxcvbnmqwertyuiopasdfghjklzxcvbnmqwertyuiopasdfghjklzxcvbnmn
- Run 7: Message extracted successfully with 100% accuracy. Extracted: So, Goddddddddd. Is good!
- Run 8: Message extracted successfully with 100% accuracy. Extracted: So, Goddddddddd. Is good!
- Run 9: Message extracted successfully with 100% accuracy. Extracted: So, Goddddddddd. Is good!
- Run 10: Message extracted successfully with 100% accuracy. Extracted: So, Goddddddddd. Is good!
- Run 11: Message extracted successfully with 100% accuracy. Extracted: So, Goddddddddd. Is good!
- Run 12: Message extracted successfully with 100% accuracy. Extracted: So, Goddddddddd. Is good!
- Run 13: Message extracted successfully with 100% accuracy. Extracted: So, Goddddddddd. Is good!
- Run 14: Message extracted successfully with 100% accuracy. Extracted: So, Goddddddddd. Is good!
- Run 15: Message extracted successfully with 100% accuracy. Extracted: So, Goddddddddd. Is good!
- Run 16: Message extracted successfully with 100% accuracy. Extracted: So, Goddddddddd. Is good!
- Run 17: Message extracted successfully with 100% accuracy. Extracted: So, Goddddddddd. Is good!
- Run 18: Message extracted successfully with 100% accuracy. Extracted: So, Goddddddddd. Is good!
- Run 19: Message extracted successfully with 100% accuracy. Extracted: So, Goddddddddd. Is good!
- Run 20: Message extracted successfully with 100% accuracy. Extracted: So, Goddddddddd. Is good!

Comparison of extraction capacities per resolution and extraction success rate is reflected in Table 2 and Table 2.1.

## B. Comparison of Different Payload Levels

### Table 3. Payload Capacity vs Quality Metrics

| Payload Capacity | MSE | PSNR | SSIM | Q Index |
|---|---:|---:|---:|---:|
| 10% | 0.003338 | 74.761612 | 0.999999 | 0.999999 |
| 25% | 0.005510 | 72.039112 | 0.999999 | 0.999999 |
| 50% | 0.004817 | 72.565067 | 0.999999 | 0.999999 |
| 75% | 0.004817 | 72.565067 | 0.999999 | 0.999999 |
| 90% | 0.009155 | 69.345817 | 0.999999 | 0.999999 |

Fig 7: Line graph of Payload vs PSNR
Fig 8: Line graph of Payload vs SSIM
Fig 9: Line graph of Payload vs MSE

Interpretation: Higher payload generally increases distortion (MSE rises, PSNR falls), while lower payload preserves imperceptibility.

## C. Relationship Between Payload Size, Image Degradation, and Extraction Accuracy

### Table 4. Payload vs PSNR, MSE, and Extraction Accuracy

| Payload | PSNR | MSE | Extraction Accuracy |
|---|---:|---:|---:|
| 10% | 74.761612 | 0.003338 | 100.00% |
| 25% | 72.039112 | 0.005510 | 100.00% |
| 50% | 72.565067 | 0.004817 | 100.00% |
| 75% | 72.565067 | 0.004817 | 100.00% |
| 90% | 69.345817 | 0.009155 | 100.00% |

Observed trend: Increasing payload capacity tends to lower PSNR values and raise MSE.
Extraction Accuracy typically remains stable at lower-to-mid payload levels and may degrade at high embedding rates depending on image content.

## D. Payload Capacity and Image Quality Recommendations

### Table 5. Recommended Payload per Resolution

| Resolution | Recommended Payload | PSNR | Extraction Accuracy | Recommendation |
|---|---:|---:|---:|---|
| 128px | 90% | 69.8476 | 100.00% | Optimal: PSNR >= 40 dB, high fidelity, and reliable extraction. |
| 256px | 90% | 68.3422 | 100.00% | Optimal: PSNR >= 40 dB, high fidelity, and reliable extraction. |
| 512px | N/A | N/A | N/A | No runs yet for this resolution. |
| 1024px | N/A | N/A | N/A | No runs yet for this resolution. |

Justification: Recommended payloads are selected to maintain PSNR above 40 dB where possible, keep SSIM near 1.0, ensure successful extraction, and minimize visible distortion.

Practical interpretation:
- 128x128: suitable for short messages.
- 256x256: suitable for longer short messages.
- 512x512: suitable for short stories.
- 1024x1024: suitable for chapter-length text.