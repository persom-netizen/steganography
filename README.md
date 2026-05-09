# Xect - Image Steganography Simulation System

A web-based quantitative analysis platform for Sequential LSB (Least Significant Bit) image steganography research.

## Overview

Xect implements a controlled experimental framework to evaluate:
- **Payload Capacity Effects**: How payload size affects image quality
- **Image Quality Degradation**: Using PSNR, MSE, SSIM, and Q-Index metrics
- **Extraction Reliability**: Message recovery accuracy under varying conditions
- **Computational Performance**: Embedding and extraction timing

## System Architecture

### Controlled Experimental Design
- **5 Payload Levels**: 1KB, 25KB, 50KB, 100KB, 150KB
- **10 Cover Images**: Resolution variety (256×256, 512×512, 1024×1024)
- **Total Simulations**: 50 (5 levels × 10 images)

### Core Components

#### 1. LSB Sequential Embedding Engine (`app/lsb_engine.py`)
- Consecutive bit embedding across RGB pixels
- Header (32-bit length) + payload encoding
- Maximum capacity calculation per image
- Extraction with accuracy verification

#### 2. Image Quality Metrics (`app/metrics.py`)
- **MSE**: Mean Squared Error (lower = better)
- **PSNR**: Peak Signal-to-Noise Ratio in dB (higher = better)
- **SSIM**: Structural Similarity Index (0-1 range)
- **Q-Index**: Universal Image Quality Index

#### 3. Visualization Engine (`app/visualization.py`)
- Payload vs PSNR/MSE/SSIM/Q-Index scatter plots
- Extraction accuracy vs payload
- Embedding/extraction timing analysis
- Histogram pixel distribution comparison
- Capacity-quality tradeoff curves

#### 4. Testing Framework (`app/testing.py`)
- **Black-Box Tests**: Image validation, file accessibility
- **White-Box Tests**: Extraction accuracy, timing analysis, recovery rates

#### 5. Simulation Orchestration (`app/simulation_engine.py`)
- Workflow: embed → extract → compute metrics → generate graphs → run tests
- Automatic status tracking (pending → running → completed)
- Simulation locking after completion

### Database Schema

```
AnalysisSession (groups 50 simulations)
├── Simulation (one image + one payload level)
│   ├── MetricResult (MSE, PSNR, SSIM, Q-Index)
│   ├── GraphResult (histogram, per-sim visualizations)
│   └── TestResult (test outcomes)
├── CoverImage (10 images per session)
└── AggregateGraphResult (session-level analysis graphs)
```

## Installation

### Prerequisites
- Python 3.8+
- MySQL 5.7+
- 50MB+ disk space for test images and outputs

### Setup

1. **Clone repository**
```bash
git clone https://github.com/persom-netizen/steganography.git
cd steganography
```

2. **Create virtual environment**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies**
```bash
pip install -r requirements.txt
```

4. **Configure environment**
```bash
cp .env.example .env
# Edit .env with MySQL credentials
```

5. **Initialize database**
```bash
python
>>> from app import create_app, db
>>> app = create_app()
>>> with app.app_context(): db.create_all()
>>> exit()
```

6. **Run application**
```bash
python run.py
```

Visit `http://localhost:5000`

## Usage

### Create Analysis Session
1. Navigate to "New Session"
2. Upload 10 cover images (PNG/BMP, 256×256 to 1024×1024)
3. System automatically creates 50 simulations

### Run Simulations
1. View session dashboard
2. Each simulation is initially "pending"
3. Click "Run" to execute individual simulations
4. Or batch-run all simulations

### View Results
- **Per-Simulation**: Individual metrics, graphs, test results
- **Per-Session**: Aggregate graphs, tradeoff curves, statistical summary
- **Locked Simulations**: Evidence preserved, cannot be re-run

### Data Outputs

Each completed simulation generates:
- **Metrics**: MSE, PSNR, SSIM, Q-Index values
- **Images**: Cover, stego (PNG), comparison
- **Graphs**: Histogram comparison
- **Test Results**: Pass/warning/fail status
- **Timing Data**: Embedding and extraction times

Session-level outputs:
- Payload vs quality scatter plots
- Capacity-quality tradeoff curves
- Performance timing graphs
- Statistical summary table

## Research Contributions

This platform provides:

1. **Quantitative Data**: 50 controlled experiments with reproducible results
2. **Quality Metrics**: Comprehensive image quality degradation analysis
3. **Performance Analysis**: Computational efficiency evaluation
4. **Statistical Evidence**: Payload-quality relationship modeling

## File Structure

```
steganography/
├── app/
│   ├── __init__.py              # Flask app factory
│   ├── models.py                # SQLAlchemy ORM models
│   ├── lsb_engine.py            # LSB embedding/extraction
│   ├── metrics.py               # Image quality metrics
│   ├── visualization.py         # Graph generation
│   ├── testing.py               # Testing framework
│   ├── simulation_engine.py     # Workflow orchestration
│   ├── utils.py                 # Helper functions
│   └── routes.py                # Flask blueprints
├── templates/                   # HTML templates
│   ├── dashboard/
│   ├── simulation/
│   ├── analytics/
│   └── testing/
├── uploads/                     # Runtime files
│   ├── stego_images/
│   ├── graphs/
│   └── test_images/
├── config.py                    # Configuration
├── requirements.txt             # Dependencies
├── .env.example                 # Environment template
└── run.py                       # Entry point
```

## Configuration

Edit `.env` for:
- MySQL connection string
- Max upload size (default 50MB)
- Flask environment (development/production)
- Secret key

## Performance Notes

- **Small images** (256×256): ~10-50ms embedding/extraction
- **Large images** (1024×1024): ~100-500ms
- **High payloads** (100KB+): May exceed image capacity

## Future Enhancements

- Batch simulation execution (async jobs)
- Advanced steganography methods (DCT, DWT)
- Steganalysis resistance analysis
- Comparative benchmarking
- Export results (PDF, CSV)

## License

Research project - Educational use

## References

[1] Kaur, M., Verma, B. K., & Kumar, A. (2018). A survey of digital image steganography.
[2] Provos, N., & Honeyman, P. (2003). Hide and seek: An introduction to steganography.
[3] Cheddad, A., Condell, J., Curran, K., & Kevitt, P. M. (2010). Digital image steganography: Survey and analysis.

---

**Author**: Research Team  
**Date**: 2026  
**Status**: Active Development
