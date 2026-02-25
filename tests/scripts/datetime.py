import json
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from app.utils.time import format_reference_context, utcnow
    
reference_dt_utc = utcnow()

# Get reference context for the prompt
ref_context = format_reference_context(reference_dt_utc, 'UTC')


json.dumps(ref_context, indent=2)