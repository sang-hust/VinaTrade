"""ICB level-2 sector codes used by Vietcap (icbCode2) → Vietnamese / English names."""

ICB_LV2: dict[str, tuple[str, str]] = {
    "0500": ("Dầu khí", "Oil & Gas"),
    "1300": ("Hóa chất", "Chemicals"),
    "1700": ("Tài nguyên cơ bản", "Basic Resources"),
    "2300": ("Xây dựng và vật liệu", "Construction & Materials"),
    "2700": ("Hàng và dịch vụ công nghiệp", "Industrial Goods & Services"),
    "3300": ("Ô tô và phụ tùng", "Automobiles & Parts"),
    "3500": ("Thực phẩm và đồ uống", "Food & Beverage"),
    "3700": ("Hàng cá nhân và gia dụng", "Personal & Household Goods"),
    "4500": ("Y tế", "Health Care"),
    "5300": ("Bán lẻ", "Retail"),
    "5500": ("Truyền thông", "Media"),
    "5700": ("Du lịch và giải trí", "Travel & Leisure"),
    "6500": ("Viễn thông", "Telecommunications"),
    "7500": ("Điện, nước, xăng dầu, khí đốt", "Utilities"),
    "8300": ("Ngân hàng", "Banks"),
    "8500": ("Bảo hiểm", "Insurance"),
    "8600": ("Bất động sản", "Real Estate"),
    "8700": ("Dịch vụ tài chính", "Financial Services"),
    "9500": ("Công nghệ thông tin", "Technology"),
}

# Macro factor → sector impacts (spec 3.5). Admin-editable copy lives in system_config "macro.sector_rules".
SECTOR_MACRO_RULES = [
    {"factor": "Lãi suất giảm, tín dụng nới lỏng", "benefit": ["8600", "8700", "8300", "2300"], "hurt": []},
    {"factor": "Đẩy mạnh đầu tư công", "benefit": ["2300", "1700"], "hurt": []},
    {"factor": "FDI tăng, dịch chuyển chuỗi cung ứng", "benefit": ["8600", "2700"], "hurt": []},
    {"factor": "Giá dầu tăng", "benefit": ["0500"], "hurt": ["5700", "1300"]},
    {"factor": "Tỷ giá tăng (VND yếu)", "benefit": ["3500", "3700", "1700"], "hurt": ["7500"]},
    {"factor": "Tiêu dùng phục hồi", "benefit": ["5300", "3500", "5700"], "hurt": []},
    {"factor": "Nâng hạng thị trường", "benefit": ["8700", "8300"], "hurt": []},
]
