#CONFIGURATION
DEFCONFIG_PATH=arch/arm64/configs/vendor/fog_defconfig # Must be edited
DEFCONFIG=vendor/fog_defconfig # Must be edited
TAG="SCRIPT"
CLEAN_KSU=0

export ARCH=arm64
export SUBARCH=arm64
export PATH="$(pwd)/toolchain/clang/bin:$PATH"

ksu_clean() {
	local is_ksu=$(grep -Eo 'CONFIG_KSU_SUSFS=[yn]$$' arch/arm64/configs/vendor/fog_defconfig | cut -d'=' -f2)

	if [ "$is_ksu" == "y" ]; then
		make -j$(nproc) O=out \
			ARCH=arm64 \
			CC=clang \
			HOSTCC=gcc \
			CROSS_COMPILE=aarch64-linux-gnu- \
			CROSS_COMPILE_ARM32=arm-linux-gnueabi- \
			AR=llvm-ar \
			NM=llvm-nm \
			OBJCOPY=llvm-objcopy \
			OBJDUMP=llvm-objdump \
			STRIP=llvm-strip \
			HAVE_KSU_HOOK=0 \
			M=drivers/kernelsu \
			clean &&
			echo "  $TAG    KernelSU clean successful"
	fi
}

while [[ $# -gt 0 ]]; do
	case $1 in
	--clean | -D)
		case ${2:-} in
		ksu)
			CLEAN_KSU=1
			;;
		all)
			# TODO
			;;
		*)
			echo "  $TAG    Unknown clean target: $2"
			exit 1
			;;
		esac
		shift 2
		;;
	*)
		echo "  $TAG    Unknown option: $1"
		exit 1
		;;
	esac
done

make -j$(nproc) O=out \
	ARCH=arm64 \
	CC=clang \
	HOSTCC=gcc \
	CROSS_COMPILE=aarch64-linux-gnu- \
	CROSS_COMPILE_ARM32=arm-linux-gnueabi- \
	AR=llvm-ar \
	NM=llvm-nm \
	OBJCOPY=llvm-objcopy \
	OBJDUMP=llvm-objdump \
	STRIP=llvm-strip \
	$DEFCONFIG

if [ $CLEAN_KSU -eq 1 ]; then
	ksu_clean
fi

make -j$(nproc) O=out \
	ARCH=arm64 \
	CC=clang \
	HOSTCC=gcc \
	CROSS_COMPILE=aarch64-linux-gnu- \
	CROSS_COMPILE_ARM32=arm-linux-gnueabi- \
	AR=llvm-ar \
	NM=llvm-nm \
	OBJCOPY=llvm-objcopy \
	OBJDUMP=llvm-objdump \
	STRIP=llvm-strip

if [ $? -eq 0 ]; then
	cat out/arch/arm64/boot/Image.gz out/arch/arm64/boot/dtb.img >out/arch/arm64/boot/Image.gz-dtb &&
		echo "  $TAG    out/arch/arm64/boot/Image.gz-dtb created successfully"
	notify-send "Kernel compile done" "make finished at $(date +%T)" 2>/dev/null && paplay /usr/share/sounds/freedesktop/stereo/complete.oga &
fi
